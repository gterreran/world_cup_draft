import random

from django.db import transaction

from leagues.models import League, LeagueMember
from tournaments.models import NationalTeam
from scoring.projections import mark_projection_entries_stale
from scoring.services import recompute_league_standings
from drafts.services import reset_draft

from .models import TeamAssignment


class AssignmentError(RuntimeError):
    pass


MAX_ASSIGNMENT_ATTEMPTS = 2_000


@transaction.atomic
def assign_teams_randomly(league: League, *, clear_existing: bool = True) -> None:
    members = list(league.members.all().order_by("display_name"))

    if not members:
        raise AssignmentError("This league has no managers yet.")

    required_teams = len(members) * league.teams_per_manager

    if clear_existing:
        TeamAssignment.objects.filter(league=league).delete()

    if league.assignment_method == League.AssignmentMethod.TIERED_RANDOM:
        assignments = _build_tiered_random_assignments_without_group_duplicates(
            league,
            members,
        )
    else:
        assignments = _build_random_assignments_without_group_duplicates(
            league,
            members,
            required_teams,
        )

    TeamAssignment.objects.bulk_create(assignments)


@transaction.atomic
def reset_assignments(
    league: League,
    *,
    unlock: bool = True,
    stale_reason: str = "Team assignments were reset.",
) -> int:
    """Clear all team assignments and reset dependent league state.

    Parameters
    ----------
    league : :class:`leagues.models.League`
        League whose assignments should be cleared.
    unlock : bool, optional
        Whether to unlock assignment setup after clearing the assignments.
    stale_reason : str, optional
        Reason stored on stale projection rows.

    Returns
    -------
    int
        Number of :class:`assignments.models.TeamAssignment` rows deleted.
    """
    deleted_count, _ = TeamAssignment.objects.filter(league=league).delete()

    league.assignments_generated_at = None
    update_fields = ["assignments_generated_at", "updated_at"]

    if unlock:
        league.assignments_locked = False
        update_fields.append("assignments_locked")

    league.save(update_fields=update_fields)

    _refresh_assignment_dependents(league, stale_reason=stale_reason)

    return deleted_count


@transaction.atomic
def assign_team_to_member(
    league: League,
    *,
    member_id: int,
    national_team_id: int,
) -> TeamAssignment:
    """Assign one unassigned national team to a league manager.

    Parameters
    ----------
    league : :class:`leagues.models.League`
        League receiving the manual assignment.
    member_id : int
        Primary key of the target :class:`leagues.models.LeagueMember`.
    national_team_id : int
        Primary key of the target :class:`tournaments.models.NationalTeam`.

    Returns
    -------
    :class:`assignments.models.TeamAssignment`
        Newly-created assignment.

    Raises
    ------
    AssignmentError
        Raised when the requested assignment would violate league constraints.
    """
    if league.is_setup_locked:
        raise AssignmentError("Unlock the league before manually editing assignments.")

    try:
        member = league.members.get(pk=member_id)
    except LeagueMember.DoesNotExist as exc:
        raise AssignmentError("Selected manager does not belong to this league.") from exc

    try:
        national_team = NationalTeam.objects.get(
            pk=national_team_id,
            tournament=league.tournament,
        )
    except NationalTeam.DoesNotExist as exc:
        raise AssignmentError("Selected team does not belong to this league tournament.") from exc

    if TeamAssignment.objects.filter(
        league=league,
        national_team=national_team,
    ).exists():
        raise AssignmentError(f"{national_team.name} is already assigned in this league.")

    current_assignments = list(
        TeamAssignment.objects.select_related("national_team")
        .filter(league=league, member=member)
        .order_by("national_team__pot", "national_team__name")
    )

    if len(current_assignments) >= league.teams_per_manager:
        raise AssignmentError(
            f"{member.display_name} already has {league.teams_per_manager} assigned team"
            f"{'s' if league.teams_per_manager != 1 else ''}."
        )

    if national_team.group:
        duplicate_group_assignment = next(
            (
                assignment
                for assignment in current_assignments
                if assignment.national_team.group == national_team.group
            ),
            None,
        )
        if duplicate_group_assignment is not None:
            raise AssignmentError(
                f"{member.display_name} already has "
                f"{duplicate_group_assignment.national_team.name} from Group "
                f"{national_team.group}."
            )

    assignment = TeamAssignment.objects.create(
        league=league,
        member=member,
        national_team=national_team,
    )

    _refresh_assignment_dependents(
        league,
        stale_reason=f"{national_team.name} was manually assigned to {member.display_name}.",
    )

    return assignment


@transaction.atomic
def remove_team_assignment(
    league: League,
    *,
    assignment_id: int,
) -> TeamAssignment:
    """Remove one assigned team from a league manager.

    Parameters
    ----------
    league : :class:`leagues.models.League`
        League owning the assignment.
    assignment_id : int
        Primary key of the assignment to remove.

    Returns
    -------
    :class:`assignments.models.TeamAssignment`
        In-memory copy of the removed assignment, useful for messages.

    Raises
    ------
    AssignmentError
        Raised when the assignment cannot be removed safely.
    """
    if league.is_setup_locked:
        raise AssignmentError("Unlock the league before manually editing assignments.")

    try:
        assignment = TeamAssignment.objects.select_related(
            "member",
            "national_team",
        ).get(pk=assignment_id, league=league)
    except TeamAssignment.DoesNotExist as exc:
        raise AssignmentError("Selected assignment does not exist in this league.") from exc

    removed_assignment = assignment
    assignment.delete()

    _refresh_assignment_dependents(
        league,
        stale_reason=(
            f"{removed_assignment.national_team.name} was removed from "
            f"{removed_assignment.member.display_name}."
        ),
    )

    return removed_assignment


def _refresh_assignment_dependents(
    league: League,
    *,
    stale_reason: str,
) -> None:
    """Refresh derived state after assignment changes."""
    recompute_league_standings(league)
    mark_projection_entries_stale(league, reason=stale_reason)
    reset_draft(league)


def _build_tiered_random_assignments_without_group_duplicates(
    league: League,
    members: list,
) -> list[TeamAssignment]:
    teams_by_pot = {}

    for pot in range(1, league.teams_per_manager + 1):
        teams = list(
            NationalTeam.objects.filter(
                tournament=league.tournament,
                pot=pot,
            ).order_by("id")
        )

        if len(teams) < len(members):
            raise AssignmentError(
                f"Not enough teams in pot {pot}. "
                f"Need {len(members)}, found {len(teams)}."
            )

        teams_by_pot[pot] = teams

    for _ in range(MAX_ASSIGNMENT_ATTEMPTS):
        assignments = []
        groups_by_member_id = {member.id: set() for member in members}

        randomized_members = members[:]

        success = True

        for pot in range(1, league.teams_per_manager + 1):
            teams = teams_by_pot[pot][:]
            random.shuffle(teams)
            random.shuffle(randomized_members)

            pot_assignments = _assign_one_team_from_pool(
                league=league,
                members=randomized_members,
                teams=teams,
                groups_by_member_id=groups_by_member_id,
            )

            if pot_assignments is None:
                success = False
                break

            assignments.extend(pot_assignments)

        if success:
            return assignments

    raise AssignmentError(
        "Could not create a valid tiered draw without assigning teams "
        "from the same group to the same manager. Try again, or relax the rule."
    )


def _build_random_assignments_without_group_duplicates(
    league: League,
    members: list,
    required_teams: int,
) -> list[TeamAssignment]:
    teams = list(
        NationalTeam.objects.filter(tournament=league.tournament).order_by("id")
    )

    if len(teams) < required_teams:
        raise AssignmentError(
            f"Not enough national teams. Need {required_teams}, found {len(teams)}."
        )

    for _ in range(MAX_ASSIGNMENT_ATTEMPTS):
        available_teams = teams[:]
        random.shuffle(available_teams)

        selected_teams = available_teams[:required_teams]
        assignments = []
        groups_by_member_id = {member.id: set() for member in members}

        success = True

        for member in members:
            member_assignments = []

            for _ in range(league.teams_per_manager):
                team = _pop_valid_team_for_member(
                    selected_teams,
                    groups_by_member_id[member.id],
                )

                if team is None:
                    success = False
                    break

                groups_by_member_id[member.id].add(team.group)
                member_assignments.append(
                    TeamAssignment(
                        league=league,
                        member=member,
                        national_team=team,
                    )
                )

            if not success:
                break

            assignments.extend(member_assignments)

        if success:
            return assignments

    raise AssignmentError(
        "Could not create a valid random draw without assigning teams "
        "from the same group to the same manager. Try again, or relax the rule."
    )


def _assign_one_team_from_pool(
    *,
    league: League,
    members: list,
    teams: list[NationalTeam],
    groups_by_member_id: dict[int, set[str]],
) -> list[TeamAssignment] | None:
    assignments = []

    for member in members:
        team = _pop_valid_team_for_member(
            teams,
            groups_by_member_id[member.id],
        )

        if team is None:
            return None

        groups_by_member_id[member.id].add(team.group)
        assignments.append(
            TeamAssignment(
                league=league,
                member=member,
                national_team=team,
            )
        )

    return assignments


def _pop_valid_team_for_member(
    teams: list[NationalTeam],
    used_groups: set[str],
) -> NationalTeam | None:
    for index, team in enumerate(teams):
        if team.group not in used_groups:
            return teams.pop(index)

    return None
