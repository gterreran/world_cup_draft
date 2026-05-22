import random

from django.db import transaction

from leagues.models import League
from tournaments.models import NationalTeam

from .models import TeamAssignment


class AssignmentError(RuntimeError):
    pass


@transaction.atomic
def assign_teams_randomly(league: League, *, clear_existing: bool = True) -> None:
    members = list(league.members.all())

    if not members:
        raise AssignmentError("This league has no managers yet.")

    required_teams = len(members) * league.teams_per_manager

    if clear_existing:
        TeamAssignment.objects.filter(league=league).delete()

    if league.use_tiers:
        _assign_tiered_randomly(league, members)
    else:
        teams = list(
            NationalTeam.objects.filter(tournament=league.tournament)
            .order_by("id")
        )

        if len(teams) < required_teams:
            raise AssignmentError(
                f"Not enough national teams. Need {required_teams}, found {len(teams)}."
            )

        random.shuffle(teams)

        assignments = []
        index = 0

        for member in members:
            for _ in range(league.teams_per_manager):
                assignments.append(
                    TeamAssignment(
                        league=league,
                        member=member,
                        national_team=teams[index],
                    )
                )
                index += 1

        TeamAssignment.objects.bulk_create(assignments)


def _assign_tiered_randomly(league: League, members: list) -> None:
    assignments = []

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

        random.shuffle(teams)

        for member, team in zip(members, teams):
            assignments.append(
                TeamAssignment(
                    league=league,
                    member=member,
                    national_team=team,
                )
            )

    TeamAssignment.objects.bulk_create(assignments)