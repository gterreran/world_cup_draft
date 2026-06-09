from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from leagues.models import League
from leagues.permissions import can_manage_league

from .jobs import ProjectionQueueUnavailable, request_projection_recompute
from .services import recompute_league_standings
from .projections import mark_projection_entries_stale


@login_required
def recompute_standings(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
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

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can recompute projections.")
        return redirect("league_detail", slug=league.slug)

    if request.method == "POST":
        try:
            result = request_projection_recompute(
                league,
                reason="Manual projection recompute requested.",
            )
        except ProjectionQueueUnavailable as exc:
            messages.error(request, str(exc))
        else:
            if result.queued:
                messages.success(request, result.message)
            else:
                messages.info(request, result.message)

    return redirect("league_detail", slug=league.slug)
