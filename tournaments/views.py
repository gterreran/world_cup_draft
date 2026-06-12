from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from leagues.models import League
from leagues.permissions import can_edit_match_results
from live_scores.display import attach_live_score_displays

from .forms import MatchResultForm
from .models import Match, Tournament
from .services import apply_final_match_result, build_group_stage_context
from collections import defaultdict

def match_list(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    matches = Match.objects.filter(
        tournament=league.tournament,
    ).select_related(
        "home_team",
        "away_team",
        "winner",
    ).order_by(
        "stage",
        "kickoff_time",
        "id",
    )

    return render(
        request,
        "tournaments/match_list.html",
        {
            "league": league,
            "matches": matches,
            "can_edit_match_results": can_edit_match_results(request.user),
        },
    )


@login_required
def match_result_edit(request, slug: str, match_id: int):
    league = get_object_or_404(League, slug=slug)
    match = get_object_or_404(Match, id=match_id, tournament=league.tournament)

    if not can_edit_match_results(request.user):
        messages.error(request, "Only platform owners can edit match results.")
        return redirect("match_list", slug=league.slug)

    if request.method == "POST":
        form = MatchResultForm(request.POST, instance=match)

        if form.is_valid():
            result = apply_final_match_result(
                match=match,
                home_score=form.cleaned_data["home_score"],
                away_score=form.cleaned_data["away_score"],
                winner=form.cleaned_data.get("winner"),
                went_to_extra_time=form.cleaned_data.get("went_to_extra_time", False),
                went_to_penalties=form.cleaned_data.get("went_to_penalties", False),
                reason="Manual match result changed.",
            )

            for warning_message in result.refresh.unavailable_messages:
                messages.warning(request, warning_message)

            messages.success(
                request,
                "Match result updated. "
                f"Recomputed standings for {result.refresh.league_count} league"
                f"{'s' if result.refresh.league_count != 1 else ''}; "
                f"queued {result.refresh.queued_count} projection recompute job"
                f"{'s' if result.refresh.queued_count != 1 else ''}.",
            )
            return redirect("match_list", slug=league.slug)
    else:
        form = MatchResultForm(instance=match)

    return render(
        request,
        "tournaments/match_result_edit.html",
        {
            "league": league,
            "match": match,
            "form": form,
        },
    )

def tournament_schedule(request, tournament_slug: str):
    tournament = get_object_or_404(Tournament, slug=tournament_slug)

    matches = (
        Match.objects.filter(tournament=tournament)
        .select_related("home_team", "away_team", "winner")
        .order_by("kickoff_time", "match_number", "id")
    )

    matches = attach_live_score_displays(matches)

    matches_by_stage = defaultdict(list)

    for match in matches:
        matches_by_stage[match.get_stage_display()].append(match)

    return render(
        request,
        "tournaments/schedule.html",
        {
            "tournament": tournament,
            "matches_by_stage": dict(matches_by_stage),
        },
    )

def group_stage(request, tournament_slug: str):
    tournament = get_object_or_404(Tournament, slug=tournament_slug)

    groups = build_group_stage_context(tournament)

    group_matches = []
    for group in groups:
        group_matches.extend(group.get("matches", []))
    attach_live_score_displays(group_matches)

    return render(
        request,
        "tournaments/group_stage.html",
        {
            "tournament": tournament,
            "groups": groups,
        },
    )



def _slot_winner_match_number(slot: str) -> int | None:
    slot = (slot or "").strip()

    if len(slot) < 2 or slot[0] != "W" or not slot[1:].isdigit():
        return None

    return int(slot[1:])


def _match_sort_key(match: Match) -> tuple:
    return (
        match.match_number or 9999,
        match.kickoff_time.isoformat() if match.kickoff_time else "",
        match.id,
    )


def _order_matches_by_bracket_path(
    *,
    matches: list[Match],
    stages: list[str],
) -> dict[str, list[Match]]:
    """Return matches ordered by bracket topology rather than match number.

    The official schedule match numbers are chronological, but the bracket UI
    needs matches ordered by the tree path. For example, if match 89 is
    ``W74`` vs ``W77``, then matches 74 and 77 need to sit next to each other
    in the Round-of-32 column, even if match 73 has a lower match number.
    """

    matches_by_number = {
        match.match_number: match
        for match in matches
        if match.match_number is not None
    }
    ordered_by_stage = {stage: [] for stage in stages}
    seen_match_ids: set[int] = set()

    def visit(match: Match | None) -> None:
        if match is None or match.id in seen_match_ids:
            return

        seen_match_ids.add(match.id)

        if match.stage in ordered_by_stage:
            ordered_by_stage[match.stage].append(match)

        for slot in (match.home_slot, match.away_slot):
            source_match_number = _slot_winner_match_number(slot)
            if source_match_number is None:
                continue

            visit(matches_by_number.get(source_match_number))

    final_matches = sorted(
        (match for match in matches if match.stage == Match.Stage.FINAL),
        key=_match_sort_key,
    )
    for match in final_matches:
        visit(match)

    # Be defensive: if the schedule is incomplete, or if a future tournament
    # contains disconnected placeholder matches, still render them in a stable
    # fallback order after the bracket-path matches.
    for stage in stages:
        remaining_matches = sorted(
            (
                match
                for match in matches
                if match.stage == stage and match.id not in seen_match_ids
            ),
            key=_match_sort_key,
        )
        ordered_by_stage[stage].extend(remaining_matches)

    return ordered_by_stage


def bracket_stage(request, tournament_slug: str):
    tournament = get_object_or_404(Tournament, slug=tournament_slug)

    championship_stages = [
        Match.Stage.ROUND_OF_32,
        Match.Stage.ROUND_OF_16,
        Match.Stage.QUARTERFINAL,
        Match.Stage.SEMIFINAL,
        Match.Stage.FINAL,
    ]

    championship_matches = list(
        Match.objects.filter(tournament=tournament, stage__in=championship_stages)
        .select_related("home_team", "away_team", "winner")
        .order_by("match_number", "id")
    )
    matches_by_stage = _order_matches_by_bracket_path(
        matches=championship_matches,
        stages=championship_stages,
    )

    championship_rounds = []
    base_match_count = 16

    for round_index, stage in enumerate(championship_stages):
        matches = attach_live_score_displays(
            Match.objects.filter(tournament=tournament, stage=stage)
            .select_related("home_team", "away_team", "winner")
            .order_by("match_number")
        )

        row_span = 2 ** round_index
        entries = []

        for index, match in enumerate(matches):
            pair_position = ""
            if stage != Match.Stage.FINAL:
                pair_position = "upper" if index % 2 == 0 else "lower"

            entries.append(
                {
                    "match": match,
                    "row_start": 1 + index * row_span,
                    "row_span": row_span,
                    "pair_position": pair_position,
                }
            )

        championship_rounds.append(
            {
                "stage": Match.Stage(stage).label,
                "stage_value": stage,
                "stage_class": stage.replace("_", "-"),
                "entries": entries,
            }
        )

    third_place_matches = attach_live_score_displays(
        Match.objects.filter(tournament=tournament, stage=Match.Stage.THIRD_PLACE)
        .select_related("home_team", "away_team", "winner")
        .order_by("match_number")
    )

    return render(
        request,
        "tournaments/bracket_stage.html",
        {
            "tournament": tournament,
            "championship_rounds": championship_rounds,
            "third_place_matches": third_place_matches,
            "base_match_count": base_match_count,
        },
    )
