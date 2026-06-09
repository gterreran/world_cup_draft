from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from leagues.models import League
from leagues.permissions import can_manage_league
from tournaments.models import NationalTeam

from .services import (
    AssignmentError,
    assign_team_to_member,
    assign_teams_randomly,
    draft_is_running,
    hide_all_assignments,
    hide_assignment,
    remove_team_assignment,
    reset_assignments,
    request_projection_recompute_when_assignments_complete,
    reveal_all_assignments,
    reveal_assignment,
)
from scoring.services import recompute_league_standings
from drafts.services import reset_draft


@login_required
def assignment_management(request, slug: str):
    """Show commissioner controls for league team assignments."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can manage assignments.")
        return redirect("league_detail", slug=league.slug)

    members = league.members.all().order_by("display_name")
    assignments = (
        league.team_assignments.select_related("member", "national_team")
        .order_by(
            "member__display_name",
            "national_team__pot",
            "national_team__name",
        )
    )

    assigned_team_ids = []
    assignments_by_member: dict[int, list] = {}
    assignment_counts_by_member: dict[int, int] = {}

    for assignment in assignments:
        assigned_team_ids.append(assignment.national_team_id)
        assignments_by_member.setdefault(assignment.member_id, []).append(assignment)
        assignment_counts_by_member[assignment.member_id] = (
            assignment_counts_by_member.get(assignment.member_id, 0) + 1
        )

    unassigned_teams = NationalTeam.objects.filter(
        tournament=league.tournament,
    ).exclude(
        id__in=assigned_team_ids,
    ).order_by("pot", "group", "name")

    return render(
        request,
        "leagues/assignment_management.html",
        {
            "league": league,
            "members": members,
            "assignments": assignments,
            "assignments_by_member": assignments_by_member,
            "assignment_counts_by_member": assignment_counts_by_member,
            "unassigned_teams": unassigned_teams,
            "draft_is_running": draft_is_running(league),
        },
    )


@login_required
def random_assignment(request, slug: str):
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
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
        request_projection_recompute_when_assignments_complete(
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


@login_required
def reset_assignment_view(request, slug: str):
    """Clear all assignments from the commissioner assignment screen."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can reset assignments.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("assignment_management", slug=league.slug)

    deleted_count = reset_assignments(league, unlock=True)

    messages.success(
        request,
        f"Reset assignments. Deleted {deleted_count} assigned team"
        f"{'s' if deleted_count != 1 else ''}, unlocked setup, and reset the draft.",
    )
    return redirect("assignment_management", slug=league.slug)


@login_required
def manual_assignment_create(request, slug: str):
    """Assign one unassigned national team to one manager."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can manually edit assignments.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("assignment_management", slug=league.slug)

    try:
        assignment = assign_team_to_member(
            league,
            member_id=int(request.POST.get("member_id", "")),
            national_team_id=int(request.POST.get("national_team_id", "")),
        )
    except (TypeError, ValueError):
        messages.error(request, "Select both a manager and a team.")
    except AssignmentError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Assigned {assignment.national_team.name} to {assignment.member.display_name}.",
        )

    return redirect("assignment_management", slug=league.slug)


@login_required
def manual_assignment_delete(request, slug: str, assignment_id: int):
    """Remove one team assignment from the commissioner assignment screen."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can manually edit assignments.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("assignment_management", slug=league.slug)

    try:
        assignment = remove_team_assignment(league, assignment_id=assignment_id)
    except AssignmentError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Removed {assignment.national_team.name} from {assignment.member.display_name}.",
        )

    return redirect("assignment_management", slug=league.slug)


@login_required
def assignment_reveal(request, slug: str, assignment_id: int):
    """Reveal one team assignment from the commissioner screens."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can reveal assignments.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("league_detail", slug=league.slug)

    try:
        assignment = reveal_assignment(league, assignment_id=assignment_id)
    except AssignmentError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Revealed {assignment.national_team.name} for {assignment.member.display_name}.",
        )

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect("league_detail", slug=league.slug)


@login_required
def assignment_hide(request, slug: str, assignment_id: int):
    """Hide one team assignment from the commissioner screens."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can hide assignments.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("league_detail", slug=league.slug)

    try:
        assignment = hide_assignment(league, assignment_id=assignment_id)
    except AssignmentError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Hid {assignment.national_team.name} for {assignment.member.display_name}.",
        )

    next_url = request.POST.get("next")
    if next_url:
        return redirect(next_url)

    return redirect("league_detail", slug=league.slug)


@login_required
def assignment_reveal_all(request, slug: str):
    """Reveal all assignments in a league."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can reveal assignments.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("assignment_management", slug=league.slug)

    revealed_count = reveal_all_assignments(league)
    messages.success(
        request,
        f"Revealed {revealed_count} hidden assignment"
        f"{'s' if revealed_count != 1 else ''}.",
    )
    return redirect("assignment_management", slug=league.slug)


@login_required
def assignment_hide_all(request, slug: str):
    """Hide all assignments in a league unless the live draft is running."""
    league = get_object_or_404(League, slug=slug)

    if not can_manage_league(request.user, league):
        messages.error(request, "Only the commissioner can hide assignments.")
        return redirect("league_detail", slug=league.slug)

    if request.method != "POST":
        return redirect("assignment_management", slug=league.slug)

    try:
        hidden_count = hide_all_assignments(league)
    except AssignmentError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(
            request,
            f"Hid {hidden_count} revealed assignment"
            f"{'s' if hidden_count != 1 else ''}.",
        )

    return redirect("assignment_management", slug=league.slug)
