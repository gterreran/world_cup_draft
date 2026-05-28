from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings

from tournaments.models import NationalTeam
from tournaments.standings import GroupStanding


# FIFA's published table columns are ordered by the group winner in the match.
# The values in each row are the third-place source group assigned opposite
# that winner. Example: {"1A": "3E"} means Winner Group A plays 3rd Group E.
FIFA_THIRD_PLACE_OPPONENT_SLOTS = (
    "1A",
    "1B",
    "1D",
    "1E",
    "1G",
    "1I",
    "1K",
    "1L",
)

GROUPS = tuple("ABCDEFGHIJKL")
CACHE_FILENAME = "fifa_2026_third_place_table.json"


@dataclass(frozen=True)
class ThirdPlaceSlot:
    slot: str
    allowed_groups: set[str]


def allocate_third_place_slots(
    *,
    qualified_third_place_teams: list[GroupStanding],
    third_place_slots_by_opponent: dict[str, str] | None = None,
    third_place_slots: list[str] | None = None,
) -> dict[str, NationalTeam]:
    """Assign third-place teams to Round-of-32 slots using FIFA's table.

    Runtime allocation intentionally does not fetch the table from the web.
    Create ``tournaments/data/fifa_2026_third_place_table.json`` beforehand
    with the ``fetch_fifa_third_place_table`` management command.

    Parameters
    ----------
    qualified_third_place_teams
        The eight qualified third-place teams, already sorted by the official
        third-place ranking.
    third_place_slots_by_opponent
        Mapping from direct group-winner slot to the corresponding schedule
        placeholder. Example: ``{"1A": "3CEFHI"}``.
    third_place_slots
        Deprecated compatibility argument. FIFA-compliant allocation requires
        ``third_place_slots_by_opponent``.

    Returns
    -------
    dict[str, NationalTeam]
        Mapping from schedule placeholder, such as ``"3CEFHI"``, to the
        concrete :class:`NationalTeam` assigned to that slot.
    """
    if third_place_slots_by_opponent is None:
        raise ValueError(
            "FIFA-compliant third-place allocation requires "
            "third_place_slots_by_opponent. Patch bracket.py so the allocator "
            "knows which placeholder is opposite 1A, 1B, 1D, 1E, 1G, 1I, "
            "1K, and 1L."
        )

    if len(qualified_third_place_teams) != 8:
        return {}

    group_to_team = {
        standing.team.group: standing.team
        for standing in qualified_third_place_teams
    }

    qualified_groups = tuple(sorted(group_to_team))

    if len(qualified_groups) != 8:
        raise ValueError(
            "Expected eight distinct qualified third-place groups; got "
            f"{qualified_groups!r}."
        )

    table = load_fifa_third_place_table()
    key = "".join(qualified_groups)

    try:
        row = table[key]
    except KeyError as exc:
        raise ValueError(
            f"No FIFA third-place allocation row found for groups {key!r}."
        ) from exc

    allocation: dict[str, NationalTeam] = {}

    for opponent_slot in FIFA_THIRD_PLACE_OPPONENT_SLOTS:
        schedule_slot = third_place_slots_by_opponent.get(opponent_slot)

        if not schedule_slot:
            raise ValueError(
                f"Missing third-place placeholder opposite {opponent_slot}."
            )

        fifa_third_slot = row[opponent_slot]
        group = fifa_third_slot[1:]

        try:
            team = group_to_team[group]
        except KeyError as exc:
            raise ValueError(
                f"FIFA table assigned {fifa_third_slot} opposite "
                f"{opponent_slot}, but group {group!r} is not among the "
                f"qualified third-place groups {key!r}."
            ) from exc

        _validate_schedule_slot_accepts_group(
            schedule_slot=schedule_slot,
            group=group,
            opponent_slot=opponent_slot,
        )

        allocation[schedule_slot] = team

    return allocation


def load_fifa_third_place_table(path: str | Path | None = None) -> dict[str, dict[str, str]]:
    """Load FIFA's 495-row third-place allocation table from local JSON.

    The file is expected at ``tournaments/data/fifa_2026_third_place_table.json``
    unless ``path`` is provided explicitly.
    """
    table_path = Path(path) if path is not None else fifa_third_place_table_path()

    if not table_path.exists():
        raise ValueError(
            f"Missing FIFA third-place allocation table: {table_path}. "
            "Run `python manage.py fetch_fifa_third_place_table` first."
        )

    with table_path.open("r", encoding="utf-8") as fh:
        table = json.load(fh)

    validate_fifa_third_place_table(table)
    return table


def fifa_third_place_table_path() -> Path:
    base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
    return base_dir / "tournaments" / "data" / CACHE_FILENAME


def validate_fifa_third_place_table(table: dict[str, dict[str, str]]) -> None:
    """Validate the local FIFA third-place allocation table shape/content."""
    if len(table) != 495:
        raise ValueError(
            "FIFA third-place allocation table should contain 495 rows; "
            f"found {len(table)}. Delete the bad JSON and rerun "
            "`python manage.py fetch_fifa_third_place_table`."
        )

    for key, row in table.items():
        if len(key) != 8 or any(group not in GROUPS for group in key):
            raise ValueError(f"Invalid FIFA third-place table key: {key!r}.")

        if list(key) != sorted(key):
            raise ValueError(
                f"Invalid FIFA third-place table key order: {key!r}. "
                "Keys should be sorted group letters."
            )

        missing_slots = set(FIFA_THIRD_PLACE_OPPONENT_SLOTS) - set(row)
        if missing_slots:
            raise ValueError(
                f"FIFA third-place table row {key!r} is missing slots "
                f"{sorted(missing_slots)!r}."
            )

        extra_slots = set(row) - set(FIFA_THIRD_PLACE_OPPONENT_SLOTS)
        if extra_slots:
            raise ValueError(
                f"FIFA third-place table row {key!r} has unexpected slots "
                f"{sorted(extra_slots)!r}."
            )

        values = list(row.values())
        if not all(isinstance(value, str) and len(value) == 2 for value in values):
            raise ValueError(
                f"FIFA third-place table row {key!r} has malformed values: "
                f"{values!r}."
            )

        if sorted(value[1:] for value in values) != sorted(key):
            raise ValueError(
                f"FIFA third-place table row {key!r} assigns invalid "
                f"third-place groups: {values!r}."
            )


def _validate_schedule_slot_accepts_group(
    *,
    schedule_slot: str,
    group: str,
    opponent_slot: str,
) -> None:
    if not schedule_slot.startswith("3"):
        raise ValueError(
            f"Slot opposite {opponent_slot} should be a third-place "
            f"placeholder; got {schedule_slot!r}."
        )

    allowed_groups = set(schedule_slot[1:])

    if group not in allowed_groups:
        raise ValueError(
            f"FIFA assigned 3{group} opposite {opponent_slot}, but schedule "
            f"placeholder {schedule_slot!r} only accepts "
            f"{''.join(sorted(allowed_groups))!r}."
        )
