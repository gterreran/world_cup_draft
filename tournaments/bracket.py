import re

from tournaments.models import Match, NationalTeam, Tournament
from tournaments.qualification import compute_qualification
from tournaments.mathematical_status import compute_guaranteed_group_slot_map
from tournaments.third_place import allocate_third_place_slots


THIRD_PLACE_SLOT_PATTERN = re.compile(r"^3([A-Z]+)$")
DIRECT_SLOT_PATTERN = re.compile(r"^[123][A-Z]$")
WINNER_SLOT_PATTERN = re.compile(r"^W(\d+)$")
LOSER_SLOT_PATTERN = re.compile(r"^L(\d+)$")


def populate_knockout_bracket(tournament: Tournament) -> None:
    qualification = compute_qualification(tournament)

    knockout_matches = (
        Match.objects.filter(tournament=tournament)
        .exclude(stage=Match.Stage.GROUP)
        .order_by("match_number")
    )

    third_place_slots_by_opponent = _collect_third_place_slots_by_opponent(
        knockout_matches
    )

    third_place_allocation = allocate_third_place_slots(
        third_place_slots_by_opponent=third_place_slots_by_opponent,
        qualified_third_place_teams=qualification.best_third_place_teams,
    )

    for match in knockout_matches:
        if match.is_complete:
            continue

        home_team = resolve_slot(
            tournament=tournament,
            slot=match.home_slot,
            qualification_map=qualification.slot_map,
            third_place_allocation=third_place_allocation,
        )

        away_team = resolve_slot(
            tournament=tournament,
            slot=match.away_slot,
            qualification_map=qualification.slot_map,
            third_place_allocation=third_place_allocation,
        )

        changed = False

        if home_team is not None and home_team != match.home_team:
            match.home_team = home_team
            changed = True

        if away_team is not None and away_team != match.away_team:
            match.away_team = away_team
            changed = True

        if changed:
            match.save()


def populate_guaranteed_group_slots(tournament: Tournament) -> None:
    """Populate known first/second-place group slots before group stage ends.

    This intentionally resolves only direct slots like ``1A`` and ``2B``.
    Third-place slots are left unresolved until the complete third-place
    allocation is known.
    """
    qualification_map = compute_guaranteed_group_slot_map(tournament)

    if not qualification_map:
        return

    knockout_matches = (
        Match.objects.filter(tournament=tournament)
        .exclude(stage=Match.Stage.GROUP)
        .order_by("match_number")
    )

    for match in knockout_matches:
        if match.is_complete:
            continue

        changed = False

        if DIRECT_SLOT_PATTERN.match((match.home_slot or "").strip()):
            home_team = qualification_map.get(match.home_slot.strip())

            if home_team is not None and home_team != match.home_team:
                match.home_team = home_team
                changed = True

        if DIRECT_SLOT_PATTERN.match((match.away_slot or "").strip()):
            away_team = qualification_map.get(match.away_slot.strip())

            if away_team is not None and away_team != match.away_team:
                match.away_team = away_team
                changed = True

        if changed:
            match.save()

def _collect_third_place_slots_by_opponent(matches) -> dict[str, str]:
    """Return {direct_winner_slot: third_place_placeholder}.

    FIFA's 2026 third-place allocation table is keyed by the group winner in
    the Round-of-32 matchup, e.g. ``1A vs 3E``. The schedule stores the
    third-place side as a compatibility placeholder such as ``3CEFHI``. This
    helper preserves the relationship between those two labels so the FIFA row
    can be translated back into the schedule's placeholder labels.
    """
    slots_by_opponent = {}

    for match in matches:
        home_slot = (match.home_slot or "").strip()
        away_slot = (match.away_slot or "").strip()

        if DIRECT_SLOT_PATTERN.match(home_slot) and THIRD_PLACE_SLOT_PATTERN.match(away_slot):
            slots_by_opponent[home_slot] = away_slot

        if DIRECT_SLOT_PATTERN.match(away_slot) and THIRD_PLACE_SLOT_PATTERN.match(home_slot):
            slots_by_opponent[away_slot] = home_slot

    return slots_by_opponent

def resolve_slot(
    *,
    tournament: Tournament,
    slot: str,
    qualification_map: dict[str, NationalTeam],
    third_place_allocation: dict[str, NationalTeam] | None = None,
) -> NationalTeam | None:
    if not slot:
        return None

    slot = slot.strip()

    direct_match = DIRECT_SLOT_PATTERN.match(slot)
    if direct_match:
        return qualification_map.get(slot)

    third_place_match = THIRD_PLACE_SLOT_PATTERN.match(slot)
    if third_place_match:
        if third_place_allocation is None:
            return None

        return third_place_allocation.get(slot)

    winner_match = WINNER_SLOT_PATTERN.match(slot)
    if winner_match:
        match_number = int(winner_match.group(1))
        return _winner_of_match(tournament, match_number)

    loser_match = LOSER_SLOT_PATTERN.match(slot)
    if loser_match:
        match_number = int(loser_match.group(1))
        return _loser_of_match(tournament, match_number)

    return None


def _winner_of_match(
    tournament: Tournament,
    match_number: int,
) -> NationalTeam | None:
    try:
        match = Match.objects.get(
            tournament=tournament,
            match_number=match_number,
        )
    except Match.DoesNotExist:
        return None

    return match.winner


def _loser_of_match(
    tournament: Tournament,
    match_number: int,
) -> NationalTeam | None:
    try:
        match = Match.objects.get(
            tournament=tournament,
            match_number=match_number,
        )
    except Match.DoesNotExist:
        return None

    if not match.is_complete:
        return None

    if not match.winner_id:
        return None

    if match.winner_id == match.home_team_id:
        return match.away_team

    return match.home_team