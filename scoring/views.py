from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from leagues.models import League

from .services import recompute_league_standings
from .projections import mark_projection_entries_stale, recompute_projection_entries


@login_required
def recompute_standings(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can recompute standings.")
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        recompute_league_standings(league)
        mark_projection_entries_stale(
            league,
            reason="Standings were recomputed.",
        )
        messages.success(
            request,
            "Standings recomputed. Max-points projections need to be recomputed.",
        )

    return redirect("league_detail", slug=league.slug)

@login_required
def recompute_projections(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can recompute projections.")
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        recompute_projection_entries(league)
        messages.success(request, "Max-points projections recomputed.")

    return redirect("league_detail", slug=league.slug)
