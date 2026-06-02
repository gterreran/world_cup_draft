from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from leagues.models import League

from .services import AssignmentError, assign_teams_randomly
from scoring.services import recompute_league_standings
from scoring.projections import mark_projection_entries_stale
from drafts.services import reset_draft


@login_required
def random_assignment(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if league.commissioner != request.user:
        messages.error(request, "Only the commissioner can assign teams.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("league_detail", slug=league.slug)

    if league.is_setup_locked:
        messages.error(request, "Unlock the league before regenerating assignments.")
        return redirect("league_detail", slug=league.slug)

    try:
        assign_teams_randomly(league)
        recompute_league_standings(league)
        mark_projection_entries_stale(
            league,
            reason="Assignments regenerated.",
        )
        reset_draft(league)
        league.lock_assignments(generated=True)
    except AssignmentError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Teams assigned successfully. League setup is now locked.")

    return redirect("league_detail", slug=league.slug)