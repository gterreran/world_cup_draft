from dataclasses import dataclass

from tournaments.models import NationalTeam
from tournaments.standings import GroupStanding


@dataclass(frozen=True)
class ThirdPlaceSlot:
    slot: str
    allowed_groups: set[str]


def allocate_third_place_slots(
    *,
    third_place_slots: list[str],
    qualified_third_place_teams: list[GroupStanding],
) -> dict[str, NationalTeam]:
    """
    Assign qualified third-place teams to bracket slots deterministically.

    The input slots look like:

        3ABCDF
        3CEFHI

    meaning that the slot accepts a third-place team from any of those groups.

    The qualified_third_place_teams list should already be sorted from best
    to worst. Each team is assigned at most once.
    """
    parsed_slots = [
        ThirdPlaceSlot(
            slot=slot,
            allowed_groups=set(slot[1:]),
        )
        for slot in third_place_slots
        if slot.startswith("3")
    ]

    remaining = list(qualified_third_place_teams)
    allocation = {}

    # Most constrained slots first. This makes the greedy allocation safer.
    parsed_slots.sort(key=lambda item: (len(item.allowed_groups), item.slot))

    for slot in parsed_slots:
        selected_index = _find_best_available_team_index(
            remaining,
            allowed_groups=slot.allowed_groups,
        )

        if selected_index is None:
            continue

        selected = remaining.pop(selected_index)
        allocation[slot.slot] = selected.team

    return allocation


def _find_best_available_team_index(
    standings: list[GroupStanding],
    *,
    allowed_groups: set[str],
) -> int | None:
    for index, standing in enumerate(standings):
        if standing.team.group in allowed_groups:
            return index

    return None