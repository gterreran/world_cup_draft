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


def bracket_stage(request, tournament_slug: str):
    tournament = get_object_or_404(Tournament, slug=tournament_slug)

    championship_stages = [
        Match.Stage.ROUND_OF_32,
        Match.Stage.ROUND_OF_16,
        Match.Stage.QUARTERFINAL,
        Match.Stage.SEMIFINAL,
        Match.Stage.FINAL,
    ]

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
