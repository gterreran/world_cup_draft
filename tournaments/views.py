from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from leagues.models import League

from .forms import MatchResultForm
from .models import Match
from scoring.services import recompute_league_standings


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