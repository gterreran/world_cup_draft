import re

from tournaments.models import Match, NationalTeam, Tournament
from tournaments.qualification import compute_qualification
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

    third_place_slots = _collect_third_place_slots(knockout_matches)

    third_place_allocation = allocate_third_place_slots(
        third_place_slots=third_place_slots,
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

def _collect_third_place_slots(matches) -> list[str]:
    slots = []

    for match in matches:
        for slot in [match.home_slot, match.away_slot]:
            if slot and THIRD_PLACE_SLOT_PATTERN.match(slot):
                slots.append(slot)

    return slots

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