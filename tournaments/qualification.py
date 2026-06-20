from dataclasses import dataclass

from tournaments.models import NationalTeam, Tournament
from tournaments.standings import GroupStanding, compute_group_standings


@dataclass
class QualificationResult:
    group_winners: dict[str, GroupStanding]
    group_runners_up: dict[str, GroupStanding]
    third_place_rankings: list[GroupStanding]
    best_third_place_teams: list[GroupStanding]
    slot_map: dict[str, NationalTeam]


def compute_qualification(tournament: Tournament) -> QualificationResult:
    standings_by_group = compute_group_standings(tournament)

    group_winners = {}
    group_runners_up = {}
    third_place_rankings = []

    for group_name, standings in standings_by_group.items():
        if len(standings) < 3:
            continue

        group_winners[group_name] = standings[0]
        group_runners_up[group_name] = standings[1]
        third_place_rankings.append(standings[2])

    third_place_rankings.sort(key=_third_place_sort_key)
    best_third_place_teams = third_place_rankings[:8]

    slot_map = _build_slot_map(
        group_winners=group_winners,
        group_runners_up=group_runners_up,
        best_third_place_teams=best_third_place_teams,
    )

    return QualificationResult(
        group_winners=group_winners,
        group_runners_up=group_runners_up,
        third_place_rankings=third_place_rankings,
        best_third_place_teams=best_third_place_teams,
        slot_map=slot_map,
    )


def _build_slot_map(
    *,
    group_winners: dict[str, GroupStanding],
    group_runners_up: dict[str, GroupStanding],
    best_third_place_teams: list[GroupStanding],
) -> dict[str, NationalTeam]:
    slot_map = {}

    for group_name, standing in group_winners.items():
        slot_map[f"1{group_name}"] = standing.team

    for group_name, standing in group_runners_up.items():
        slot_map[f"2{group_name}"] = standing.team

    for standing in best_third_place_teams:
        group_name = standing.team.group
        slot_map[f"3{group_name}"] = standing.team

    return slot_map


def _third_place_sort_key(standing: GroupStanding) -> tuple:
    # Third-place teams are ranked across groups, so head-to-head criteria do
    # not apply. The app does not currently track FIFA team conduct/fair-play
    # points, so FIFA ranking is the next deterministic fallback before name.
    return (
        -standing.points,
        -standing.goal_difference,
        -standing.goals_for,
        standing.team.fifa_rank or 10_000,
        standing.team.name,
    )
