import random

from django.db import transaction

from leagues.models import League
from tournaments.models import NationalTeam

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
    existing_groups: set[str],
) -> NationalTeam | None:
    for index, team in enumerate(teams):
        if not team.group:
            return teams.pop(index)

        if team.group not in existing_groups:
            return teams.pop(index)

    return None