from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from leagues.models import League

from .forms import MatchResultForm
from .models import Match
from .services import build_group_stage_context
from scoring.services import recompute_league_standings
from collections import defaultdict


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

    matches_by_stage = defaultdict(list)

    for match in matches:
        matches_by_stage[match.get_stage_display()].append(match)

    return render(
        request,
        "tournaments/schedule.html",
        {
            "league": league,
            "matches_by_stage": dict(matches_by_stage),
        },
    )

@login_required
def group_stage(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    groups = build_group_stage_context(league.tournament)

    return render(
        request,
        "tournaments/group_stage.html",
        {
            "league": league,
            "groups": groups,
        },
    )


@login_required
def bracket_stage(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    bracket_stages = [
        Match.Stage.ROUND_OF_32,
        Match.Stage.ROUND_OF_16,
        Match.Stage.QUARTERFINAL,
        Match.Stage.SEMIFINAL,
        Match.Stage.THIRD_PLACE,
        Match.Stage.FINAL,
    ]

    rounds = []

    for stage in bracket_stages:
        matches = (
            Match.objects.filter(tournament=league.tournament, stage=stage)
            .select_related("home_team", "away_team", "winner")
            .order_by("match_number")
        )

        rounds.append({
            "stage": Match.Stage(stage).label,
            "matches": matches,
        })

    return render(
        request,
        "tournaments/bracket_stage.html",
        {
            "league": league,
            "rounds": rounds,
        },
    )