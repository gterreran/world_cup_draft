from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from leagues.models import League

from .services import recompute_league_standings


@login_required
def recompute_standings(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can recompute standings.")
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        recompute_league_standings(league)
        messages.success(request, "Standings recomputed.")

    return redirect("league_detail", slug=league.slug)