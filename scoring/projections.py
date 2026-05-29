from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import permutations, product
import re

from django.db import transaction
from django.utils import timezone

from leagues.models import League, LeagueMember
from scoring.defaults import default_scoring_config
from scoring.models import ProjectionEntry, StandingEntry
from tournaments.models import Match, NationalTeam, TeamTournamentStatus
from tournaments.qualification import compute_qualification

from tournaments.third_place import load_fifa_third_place_table
    


DIRECT_SLOT_RE = re.compile(r"^[12][A-L]$")
THIRD_PLACEHOLDER_RE = re.compile(r"^3[A-L]+$")
WINNER_SLOT_RE = re.compile(r"^W(\d+)$")
LOSER_SLOT_RE = re.compile(r"^L(\d+)$")

TABLE_POINTS_PER_RESULT = {
    "home": (3, 0),
    "draw": (1, 1),
    "away": (0, 3),
}


@dataclass(frozen=True)
class TeamExitOption:
    """One reachable future path into, or out of, the knockout bracket."""

    team_id: int
    group_position: int | None
    slot: str | None
    group_future_points: Decimal
    third_group: str | None = None


@dataclass(frozen=True)
class ManagerMaxPointsProjection:
    """Maximum reachable fantasy score for one league member."""

    member: LeagueMember
    current_points: Decimal
    max_possible_points: Decimal
    remaining_possible_points: Decimal
    best_case_slots: dict[int, str | None]




def get_projection_entries_by_member_id(
    league: League,
) -> dict[int, ProjectionEntry]:
    """Return cached max-points projections keyed by league member id."""
    return {
        entry.member_id: entry
        for entry in ProjectionEntry.objects.filter(league=league).select_related("member")
    }


def mark_projection_entries_stale(
    league: League,
    *,
    reason: str = "Tournament state changed.",
) -> None:
    """Mark cached projections stale without recalculating them.

    This is intentionally cheap, so it is safe to call after score edits,
    assignment changes, or scoring-configuration changes.
    """
    ProjectionEntry.objects.filter(league=league).update(
        is_stale=True,
        stale_reason=reason[:160],
    )


def ensure_projection_entries_exist(
    league: League,
    *,
    reason: str = "Projection has not been calculated yet.",
) -> None:
    """Create stale placeholder projection rows for current league members."""
    existing_member_ids = set(
        ProjectionEntry.objects.filter(league=league).values_list("member_id", flat=True)
    )

    placeholders = []

    for member in league.members.all():
        if member.id in existing_member_ids:
            continue

        placeholders.append(
            ProjectionEntry(
                league=league,
                member=member,
                is_stale=True,
                stale_reason=reason,
            )
        )

    if placeholders:
        ProjectionEntry.objects.bulk_create(placeholders, ignore_conflicts=True)


def recompute_projection_entries(
    league: League,
    *,
    verbose: bool = True,
) -> dict[int, ProjectionEntry]:
    """Recompute and cache max-points projections for every league member.

    This performs the expensive search intentionally and stores the result so
    normal dashboard rendering can stay fast.
    """
    projections = compute_league_max_points_projections(league)
    now = timezone.now()

    with transaction.atomic():
        # Remove cache rows for deleted managers.
        current_member_ids = set(league.members.values_list("id", flat=True))
        ProjectionEntry.objects.filter(league=league).exclude(
            member_id__in=current_member_ids
        ).delete()

        for member_id, projection in projections.items():
            ProjectionEntry.objects.update_or_create(
                league=league,
                member=projection.member,
                defaults={
                    "current_points": projection.current_points,
                    "max_possible_points": projection.max_possible_points,
                    "remaining_possible_points": projection.remaining_possible_points,
                    "best_case_slots": {
                        str(team_id): slot
                        for team_id, slot in projection.best_case_slots.items()
                    },
                    "is_stale": False,
                    "stale_reason": "",
                    "computed_at": now,
                },
            )

    if verbose:
        print(
            f"[projections] Cached {len(projections)} projection rows for "
            f"league={league.slug!r}."
        )

    return get_projection_entries_by_member_id(league)


def compute_league_max_points_projections(
    league: League,
) -> dict[int, ManagerMaxPointsProjection]:
    """Compute the true reachable maximum score for every league member.

    The calculation is manager-local: it optimizes the paths of the teams owned
    by one manager while treating unowned teams as beatable whenever the bracket
    permits it. The real database state is only read, never mutated.
    """
    standings_by_member_id = {
        entry.member_id: entry
        for entry in StandingEntry.objects.filter(league=league).select_related("member")
    }

    projections: dict[int, ManagerMaxPointsProjection] = {}

    for member in league.members.all():
        projections[member.id] = compute_member_max_points_projection(
            league=league,
            member=member,
            standing_entry=standings_by_member_id.get(member.id),
        )

    return projections


def compute_member_max_points_projection(
    *,
    league: League,
    member: LeagueMember,
    standing_entry: StandingEntry | None = None,
) -> ManagerMaxPointsProjection:
    """Compute the maximum reachable total for one manager."""
    current_points = (
        Decimal(standing_entry.points)
        if standing_entry is not None
        else Decimal("0")
    )

    teams = list(
        NationalTeam.objects.filter(
            fantasy_assignments__league=league,
            fantasy_assignments__member=member,
        ).order_by("group", "name")
    )

    if not teams:
        return ManagerMaxPointsProjection(
            member=member,
            current_points=current_points,
            max_possible_points=current_points,
            remaining_possible_points=Decimal("0"),
            best_case_slots={},
        )

    context = _ProjectionContext(league=league, owned_team_ids={team.id for team in teams})
    option_groups = context.exit_option_groups_for_teams(teams)

    best_remaining = Decimal("0")
    best_slots: dict[int, str | None] = {team.id: None for team in teams}

    for grouped_options in product(*option_groups):
        option_combo = tuple(option for group in grouped_options for option in group)

        for slot_to_team, display_slots in context.expand_third_place_slots(option_combo):
            if not _slot_map_has_unique_teams(slot_to_team):
                continue

            group_points = sum(
                (option.group_future_points for option in option_combo),
                Decimal("0"),
            )
            knockout_points = context.max_future_knockout_points(slot_to_team)
            remaining = group_points + knockout_points

            if remaining > best_remaining:
                best_remaining = remaining
                best_slots = {
                    option.team_id: display_slots.get(option.team_id, option.slot)
                    for option in option_combo
                }

    return ManagerMaxPointsProjection(
        member=member,
        current_points=current_points,
        max_possible_points=current_points + best_remaining,
        remaining_possible_points=best_remaining,
        best_case_slots=best_slots,
    )


class _ProjectionContext:
    def __init__(self, *, league: League, owned_team_ids: set[int]):
        self.league = league
        self.tournament = league.tournament
        self.owned_team_ids = owned_team_ids
        self.config = default_scoring_config() | league.scoring_config
        self.group_stage_complete = _all_group_matches_complete(self.tournament)
        self.knockout_matches = list(
            Match.objects.filter(tournament=self.tournament)
            .exclude(stage=Match.Stage.GROUP)
            .select_related("home_team", "away_team", "winner")
            .order_by("match_number")
        )
        self.matches_by_number = {
            match.match_number: match
            for match in self.knockout_matches
            if match.match_number is not None
        }
        self.third_slots_by_opponent = _third_slots_by_opponent(self.knockout_matches)
        self.fifa_table = _load_fifa_table_or_none()
        self.min_third_points_by_group = _minimum_possible_third_points_by_group(
            self.tournament
        )
        self.actual_slot_by_team = _actual_knockout_slot_by_team(
            tournament=self.tournament,
            group_stage_complete=self.group_stage_complete,
            third_slots_by_opponent=self.third_slots_by_opponent,
            fifa_table=self.fifa_table,
        )

    def exit_option_groups_for_teams(
        self,
        teams: list[NationalTeam],
    ) -> list[list[tuple[TeamExitOption, ...]]]:
        """Return candidate option groups, preserving same-group compatibility."""
        immediate_groups: list[list[tuple[TeamExitOption, ...]]] = []
        group_stage_teams_by_group: dict[str, list[NationalTeam]] = {}

        for team in teams:
            immediate = self._immediate_option_for_team(team)

            if immediate is not None:
                immediate_groups.append([(immediate,)])
                continue

            if team.group:
                group_stage_teams_by_group.setdefault(team.group, []).append(team)
            else:
                immediate_groups.append([
                    (
                        TeamExitOption(
                            team_id=team.id,
                            group_position=None,
                            slot=None,
                            group_future_points=Decimal("0"),
                        ),
                    )
                ])

        for group, group_teams in group_stage_teams_by_group.items():
            immediate_groups.append(self._group_stage_exit_combos(group, group_teams))

        return immediate_groups or [[tuple()]]

    def _immediate_option_for_team(self, team: NationalTeam) -> TeamExitOption | None:
        if _team_is_eliminated_from_future(team):
            return TeamExitOption(
                team_id=team.id,
                group_position=None,
                slot=None,
                group_future_points=Decimal("0"),
            )

        actual_slot = self.actual_slot_by_team.get(team.id)

        if actual_slot is not None:
            return TeamExitOption(
                team_id=team.id,
                group_position=None,
                slot=actual_slot,
                group_future_points=self._future_qualification_bonus(team, actual_slot),
            )

        if self.group_stage_complete:
            # If the group stage is complete and the team has no official slot,
            # it cannot contribute future points.
            return TeamExitOption(
                team_id=team.id,
                group_position=None,
                slot=None,
                group_future_points=Decimal("0"),
            )

        return None

    def _group_stage_exit_combos(
        self,
        group: str,
        owned_teams: list[NationalTeam],
    ) -> list[tuple[TeamExitOption, ...]]:
        matches = list(
            Match.objects.filter(
                tournament=self.tournament,
                stage=Match.Stage.GROUP,
                group=group,
            )
            .select_related("home_team", "away_team")
            .order_by("match_number")
        )

        team_ids = list(
            NationalTeam.objects.filter(
                tournament=self.tournament,
                group=group,
            ).values_list("id", flat=True)
        )

        base_points = {team_id: 0 for team_id in team_ids}
        remaining_matches = []

        for match in matches:
            if match.is_complete:
                _apply_group_table_result(base_points, match)
            else:
                remaining_matches.append(match)

        owned_ids = {team.id for team in owned_teams}
        owned_by_id = {team.id: team for team in owned_teams}
        combos: dict[tuple[TeamExitOption, ...], None] = {}

        for outcomes in product(("home", "draw", "away"), repeat=len(remaining_matches)):
            scenario_points = dict(base_points)
            future_group_points = {team_id: Decimal("0") for team_id in owned_ids}

            for match, outcome in zip(remaining_matches, outcomes):
                home_table_points, away_table_points = TABLE_POINTS_PER_RESULT[outcome]
                scenario_points[match.home_team_id] += home_table_points
                scenario_points[match.away_team_id] += away_table_points

                home_fantasy_points, away_fantasy_points = self._fantasy_group_points(outcome)

                if match.home_team_id in owned_ids:
                    future_group_points[match.home_team_id] += home_fantasy_points
                if match.away_team_id in owned_ids:
                    future_group_points[match.away_team_id] += away_fantasy_points

            for ranking in _possible_rankings_from_points(scenario_points):
                option_combo = []

                for team_id in sorted(owned_ids):
                    team = owned_by_id[team_id]
                    position = ranking[team_id]
                    slot = self._direct_slot_for_position(team.group, position)
                    third_group = None
                    option_points = future_group_points[team_id]

                    if position == 3:
                        if self._third_place_points_can_qualify(
                            group=team.group,
                            points=scenario_points[team_id],
                        ):
                            third_group = team.group
                            option_points += self._future_qualification_bonus(team, "3")
                        else:
                            slot = None
                    elif slot is not None:
                        option_points += self._future_qualification_bonus(team, slot)

                    option_combo.append(
                        TeamExitOption(
                            team_id=team.id,
                            group_position=position,
                            slot=slot,
                            group_future_points=option_points,
                            third_group=third_group,
                        )
                    )

                combos[tuple(option_combo)] = None

        if not combos:
            return [
                tuple(
                    TeamExitOption(
                        team_id=team.id,
                        group_position=None,
                        slot=None,
                        group_future_points=Decimal("0"),
                    )
                    for team in owned_teams
                )
            ]

        return list(combos)

    def _fantasy_group_points(self, outcome: str) -> tuple[Decimal, Decimal]:
        if outcome == "home":
            return Decimal(str(self.config["group_win"])), Decimal(str(self.config["group_loss"]))
        if outcome == "away":
            return Decimal(str(self.config["group_loss"])), Decimal(str(self.config["group_win"]))
        return Decimal(str(self.config["group_draw"])), Decimal(str(self.config["group_draw"]))

    def _direct_slot_for_position(self, group: str, position: int) -> str | None:
        if position == 1:
            return f"1{group}"
        if position == 2:
            return f"2{group}"
        return None

    def _third_place_points_can_qualify(self, *, group: str, points: int) -> bool:
        # A third-place team is still alive if fewer than eight other groups are
        # guaranteed to produce a strictly higher third-place point total. Equal
        # point totals remain reachable because real tiebreakers are not known
        # until those matches have been played.
        groups_guaranteed_above = 0

        for other_group, min_points in self.min_third_points_by_group.items():
            if other_group == group or min_points is None:
                continue
            if min_points > points:
                groups_guaranteed_above += 1

        return groups_guaranteed_above < 8

    def _future_qualification_bonus(self, team: NationalTeam, slot: str | None) -> Decimal:
        if slot is None:
            return Decimal("0")

        try:
            status = team.tournament_status
        except TeamTournamentStatus.DoesNotExist:
            already_advanced = False
        else:
            already_advanced = status.advanced_from_group

        if already_advanced:
            return Decimal("0")

        return Decimal(str(self.config["qualify_knockout"]))

    def expand_third_place_slots(
        self,
        option_combo: tuple[TeamExitOption, ...],
    ) -> list[tuple[dict[str, int], dict[int, str | None]]]:
        """Expand generic 3rd-place exits into FIFA-compliant schedule slots."""
        slot_to_team = {
            option.slot: option.team_id
            for option in option_combo
            if option.slot is not None
        }
        display_slots = {
            option.team_id: option.slot
            for option in option_combo
        }

        third_options = [option for option in option_combo if option.third_group]

        if not third_options:
            return [(slot_to_team, display_slots)]

        if self.fifa_table is None:
            return []

        required_groups = {option.third_group for option in third_options if option.third_group}
        expansions = []

        for qualified_groups_key, row in self.fifa_table.items():
            qualified_groups = set(qualified_groups_key)

            if not required_groups.issubset(qualified_groups):
                continue

            expanded_slots = dict(slot_to_team)
            expanded_display_slots = dict(display_slots)
            valid = True

            for option in third_options:
                fifa_group_slot = f"3{option.third_group}"
                opponent_slot = _opponent_slot_for_third_group(row, fifa_group_slot)

                if opponent_slot is None:
                    valid = False
                    break

                schedule_slot = self.third_slots_by_opponent.get(opponent_slot)

                if not schedule_slot:
                    valid = False
                    break

                if option.third_group not in schedule_slot[1:]:
                    valid = False
                    break

                existing_team_id = expanded_slots.get(schedule_slot)

                if existing_team_id is not None and existing_team_id != option.team_id:
                    valid = False
                    break

                expanded_slots[schedule_slot] = option.team_id
                expanded_display_slots[option.team_id] = schedule_slot

            if valid:
                expansions.append((expanded_slots, expanded_display_slots))

        return expansions

    def max_future_knockout_points(self, slot_to_team: dict[str, int]) -> Decimal:
        return self._search_knockout(
            match_index=0,
            slot_to_team=slot_to_team,
            winners={},
            losers={},
            points=Decimal("0"),
        )

    def _search_knockout(
        self,
        *,
        match_index: int,
        slot_to_team: dict[str, int],
        winners: dict[int, int | None],
        losers: dict[int, int | None],
        points: Decimal,
    ) -> Decimal:
        if match_index >= len(self.knockout_matches):
            return points

        match = self.knockout_matches[match_index]
        match_number = match.match_number

        home = self._resolve_participant(
            match=match,
            side="home",
            slot_to_team=slot_to_team,
            winners=winners,
            losers=losers,
        )
        away = self._resolve_participant(
            match=match,
            side="away",
            slot_to_team=slot_to_team,
            winners=winners,
            losers=losers,
        )

        if match.is_complete:
            winner = _owned_or_none(match.winner_id, self.owned_team_ids)
            loser = _owned_or_none(_actual_loser_id(match), self.owned_team_ids)
            next_winners = dict(winners)
            next_losers = dict(losers)

            if match_number is not None:
                next_winners[match_number] = winner
                next_losers[match_number] = loser

            return self._search_knockout(
                match_index=match_index + 1,
                slot_to_team=slot_to_team,
                winners=next_winners,
                losers=next_losers,
                points=points,
            )

        best = points

        for winner, loser in _winner_loser_branches(home, away):
            branch_points = points + self._future_match_points(
                match=match,
                winner=winner,
                loser=loser,
            )
            next_winners = dict(winners)
            next_losers = dict(losers)

            if match_number is not None:
                next_winners[match_number] = winner
                next_losers[match_number] = loser

            candidate = self._search_knockout(
                match_index=match_index + 1,
                slot_to_team=slot_to_team,
                winners=next_winners,
                losers=next_losers,
                points=branch_points,
            )

            if candidate > best:
                best = candidate

        return best

    def _resolve_participant(
        self,
        *,
        match: Match,
        side: str,
        slot_to_team: dict[str, int],
        winners: dict[int, int | None],
        losers: dict[int, int | None],
    ) -> int | None:
        actual_team_id = match.home_team_id if side == "home" else match.away_team_id

        if actual_team_id:
            return _owned_or_none(actual_team_id, self.owned_team_ids)

        slot = (match.home_slot if side == "home" else match.away_slot) or ""
        slot = slot.strip()

        if DIRECT_SLOT_RE.match(slot) or THIRD_PLACEHOLDER_RE.match(slot):
            return _owned_or_none(slot_to_team.get(slot), self.owned_team_ids)

        winner_match = WINNER_SLOT_RE.match(slot)
        if winner_match:
            return winners.get(int(winner_match.group(1)))

        loser_match = LOSER_SLOT_RE.match(slot)
        if loser_match:
            return losers.get(int(loser_match.group(1)))

        return None

    def _future_match_points(
        self,
        *,
        match: Match,
        winner: int | None,
        loser: int | None,
    ) -> Decimal:
        points = Decimal("0")

        if winner is not None:
            points += Decimal(str(self.config["knockout_win_regulation"]))

        # For max points, owned teams are assumed to win or lose in regulation.
        # Knockout loss points are therefore zero with the default config. If the
        # league gives loss points only for ET/penalty losses, choosing regulation
        # is still the clean conservative representative for a deterministic max.
        if match.stage == Match.Stage.FINAL:
            if winner is not None:
                points += Decimal(str(self.config["champion_bonus"]))
            if loser is not None:
                points += Decimal(str(self.config["runner_up_bonus"]))

        elif match.stage == Match.Stage.THIRD_PLACE:
            if winner is not None:
                points += Decimal(str(self.config["third_place_bonus"]))
            if loser is not None:
                points += Decimal(str(self.config["fourth_place_bonus"]))

        return points


def _slot_map_has_unique_teams(slot_to_team: dict[str, int]) -> bool:
    team_ids = list(slot_to_team.values())
    return len(team_ids) == len(set(team_ids))


def _possible_rankings_from_points(points: dict[int, int]) -> list[dict[int, int]]:
    """Return all point-compatible rankings, preserving real tie ambiguity."""
    grouped: dict[int, list[int]] = {}

    for team_id, team_points in points.items():
        grouped.setdefault(team_points, []).append(team_id)

    point_groups = []
    current_position = 1

    for team_points in sorted(grouped, reverse=True):
        tied_team_ids = sorted(grouped[team_points])
        point_groups.append((current_position, tied_team_ids))
        current_position += len(tied_team_ids)

    rankings = [{}]

    for start_position, tied_team_ids in point_groups:
        next_rankings = []

        for ordered_team_ids in permutations(tied_team_ids):
            position_map = {
                team_id: start_position + offset
                for offset, team_id in enumerate(ordered_team_ids)
            }

            for ranking in rankings:
                merged = dict(ranking)
                merged.update(position_map)
                next_rankings.append(merged)

        rankings = next_rankings

    return rankings


def _apply_group_table_result(points: dict[int, int], match: Match) -> None:
    if match.home_score > match.away_score:
        points[match.home_team_id] += 3
    elif match.away_score > match.home_score:
        points[match.away_team_id] += 3
    else:
        points[match.home_team_id] += 1
        points[match.away_team_id] += 1


def _minimum_possible_third_points_by_group(tournament) -> dict[str, int | None]:
    groups = list(
        NationalTeam.objects.filter(tournament=tournament)
        .exclude(group="")
        .values_list("group", flat=True)
        .distinct()
        .order_by("group")
    )

    return {
        group: _minimum_possible_third_points(tournament, group)
        for group in groups
    }


def _minimum_possible_third_points(tournament, group: str) -> int | None:
    teams = list(
        NationalTeam.objects.filter(tournament=tournament, group=group)
        .values_list("id", flat=True)
    )
    matches = list(
        Match.objects.filter(
            tournament=tournament,
            stage=Match.Stage.GROUP,
            group=group,
        ).order_by("match_number")
    )

    if not teams or not matches:
        return None

    base_points = {team_id: 0 for team_id in teams}
    remaining_matches = []

    for match in matches:
        if match.is_complete:
            _apply_group_table_result(base_points, match)
        else:
            remaining_matches.append(match)

    min_third = None

    for outcomes in product(("home", "draw", "away"), repeat=len(remaining_matches)):
        scenario_points = dict(base_points)

        for match, outcome in zip(remaining_matches, outcomes):
            home_points, away_points = TABLE_POINTS_PER_RESULT[outcome]
            scenario_points[match.home_team_id] += home_points
            scenario_points[match.away_team_id] += away_points

        for ranking in _possible_rankings_from_points(scenario_points):
            third_points = next(
                scenario_points[team_id]
                for team_id, position in ranking.items()
                if position == 3
            )

            if min_third is None or third_points < min_third:
                min_third = third_points

    return min_third


def _third_slots_by_opponent(matches: list[Match]) -> dict[str, str]:
    slots_by_opponent = {}

    for match in matches:
        home_slot = (match.home_slot or "").strip()
        away_slot = (match.away_slot or "").strip()

        if DIRECT_SLOT_RE.match(home_slot) and THIRD_PLACEHOLDER_RE.match(away_slot):
            slots_by_opponent[home_slot] = away_slot

        if DIRECT_SLOT_RE.match(away_slot) and THIRD_PLACEHOLDER_RE.match(home_slot):
            slots_by_opponent[away_slot] = home_slot

    return slots_by_opponent


def _load_fifa_table_or_none() -> dict[str, dict[str, str]] | None:
    if load_fifa_third_place_table is None:
        return None

    try:
        return load_fifa_third_place_table()
    except Exception:
        return None


def _opponent_slot_for_third_group(
    fifa_row: dict[str, str],
    fifa_group_slot: str,
) -> str | None:
    for opponent_slot, value in fifa_row.items():
        if value == fifa_group_slot:
            return opponent_slot
    return None


def _actual_knockout_slot_by_team(
    *,
    tournament,
    group_stage_complete: bool,
    third_slots_by_opponent: dict[str, str],
    fifa_table: dict[str, dict[str, str]] | None,
) -> dict[int, str]:
    slot_by_team: dict[int, str] = {}

    # Prefer teams already placed into future bracket matches. This captures
    # early Q1/Q2 bracket propagation and later knockout winners.
    for match in Match.objects.filter(tournament=tournament).exclude(stage=Match.Stage.GROUP):
        if match.is_complete:
            continue

        if match.home_team_id:
            slot_by_team[match.home_team_id] = (match.home_slot or f"M{match.match_number}:home").strip()
        if match.away_team_id:
            slot_by_team[match.away_team_id] = (match.away_slot or f"M{match.match_number}:away").strip()

    # Official final group-stage slots are safe only after every group match is
    # complete. Before then, compute_qualification() reflects the current table,
    # not a final or mathematically guaranteed outcome.
    if not group_stage_complete:
        return slot_by_team

    try:
        qualification = compute_qualification(tournament)
    except Exception:
        return slot_by_team

    for slot, team in qualification.slot_map.items():
        if team is not None:
            slot_by_team.setdefault(team.id, slot)

    if fifa_table is None:
        return slot_by_team

    third_group_to_team = {
        standing.team.group: standing.team
        for standing in qualification.best_third_place_teams
    }

    if len(third_group_to_team) != 8:
        return slot_by_team

    key = "".join(sorted(third_group_to_team))
    row = fifa_table.get(key)

    if not row:
        return slot_by_team

    for opponent_slot, fifa_slot in row.items():
        schedule_slot = third_slots_by_opponent.get(opponent_slot)

        if not schedule_slot or not fifa_slot:
            continue

        team = third_group_to_team.get(fifa_slot[1:])

        if team is not None:
            slot_by_team.setdefault(team.id, schedule_slot)

    return slot_by_team


def _team_is_eliminated_from_future(team: NationalTeam) -> bool:
    try:
        status = team.tournament_status
    except TeamTournamentStatus.DoesNotExist:
        return False

    if status.finish_rank is not None:
        return True

    if status.mathematically_eliminated and not status.advanced_from_group:
        return True

    return False


def _all_group_matches_complete(tournament) -> bool:
    group_matches = Match.objects.filter(tournament=tournament, stage=Match.Stage.GROUP)
    return group_matches.exists() and all(match.is_complete for match in group_matches)


def _owned_or_none(team_id: int | None, owned_team_ids: set[int]) -> int | None:
    if team_id in owned_team_ids:
        return team_id
    return None


def _actual_loser_id(match: Match) -> int | None:
    if not match.winner_id:
        return None
    if match.winner_id == match.home_team_id:
        return match.away_team_id
    return match.home_team_id


def _winner_loser_branches(
    home: int | None,
    away: int | None,
) -> list[tuple[int | None, int | None]]:
    if home is None and away is None:
        return [(None, None)]

    if home is not None and away is None:
        return [(home, None)]

    if home is None and away is not None:
        return [(away, None)]

    if home == away:
        return [(home, None)]

    return [(home, away), (away, home)]
