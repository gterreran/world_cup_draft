from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from leagues.models import League

from .forms import MatchResultForm
from .models import Match
from .services import build_group_stage_context
from scoring.services import recompute_league_standings
from collections import defaultdict
from assignments.models import TeamAssignment
from tournaments.progression import recompute_tournament_progression

@login_required
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
        },
    )


@login_required
def match_result_edit(request, slug: str, match_id: int):
    league = get_object_or_404(League, slug=slug)
    match = get_object_or_404(Match, id=match_id, tournament=league.tournament)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can edit match results.")
        return redirect("match_list", slug=league.slug)

    if request.method == "POST":
        form = MatchResultForm(request.POST, instance=match)

        if form.is_valid():
            form.save()

            recompute_tournament_progression(league.tournament)
            recompute_league_standings(league)
            messages.success(request, "Match result updated and standings recomputed.")
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

@login_required
def tournament_schedule(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    matches = (
        Match.objects.filter(tournament=league.tournament)
        .select_related("home_team", "away_team", "winner")
        .order_by("kickoff_time", "match_number", "id")
    )

    assignment_map = {
        assignment.national_team_id: assignment.member.display_name
        for assignment in (
            TeamAssignment.objects
            .filter(league=league)
            .select_related("member", "national_team")
        )
    }

    matches_by_stage = defaultdict(list)

    for match in matches:
        matches_by_stage[match.get_stage_display()].append(match)

    return render(
        request,
        "tournaments/schedule.html",
        {
            "league": league,
            "matches_by_stage": dict(matches_by_stage),
            "assignment_map": assignment_map,
        },
    )

@login_required
def group_stage(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    groups = build_group_stage_context(league.tournament)

    assignment_map = {
        assignment.national_team_id: assignment.member.display_name
        for assignment in (
            TeamAssignment.objects
            .filter(league=league)
            .select_related("member", "national_team")
        )
    }

    return render(
        request,
        "tournaments/group_stage.html",
        {
            "league": league,
            "groups": groups,
            "assignment_map": assignment_map,
        },
    )


@login_required
def bracket_stage(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    assignment_map = {
        assignment.national_team_id: assignment.member.display_name
        for assignment in (
            TeamAssignment.objects
            .filter(league=league)
            .select_related("member", "national_team")
        )
    }

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
        matches = list(
            Match.objects.filter(tournament=league.tournament, stage=stage)
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

    third_place_matches = list(
        Match.objects.filter(tournament=league.tournament, stage=Match.Stage.THIRD_PLACE)
        .select_related("home_team", "away_team", "winner")
        .order_by("match_number")
    )

    return render(
        request,
        "tournaments/bracket_stage.html",
        {
            "league": league,
            "championship_rounds": championship_rounds,
            "third_place_matches": third_place_matches,
            "base_match_count": base_match_count,
            "assignment_map": assignment_map,
        },
    )
