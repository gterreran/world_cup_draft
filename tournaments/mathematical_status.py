# `tournaments/mathematical_status.py`
from dataclasses import dataclass
from collections import defaultdict
from itertools import product

from tournaments.models import Match, NationalTeam
from tournaments.standings import compute_group_standings


@dataclass(frozen=True)
class GroupResultRecord:
    """Remaining group-stage W/D/L record for one team in one scenario.

    The record intentionally counts only matches that have not yet been
    completed. This makes it directly useful for projection logic, where the
    current fantasy score is already known and only remaining points should be
    maximized.
    """

    wins: int = 0
    draws: int = 0
    losses: int = 0


@dataclass
class PositionOutcomeEnvelope:
    """Compact description of how a team can still reach one position."""

    position: int
    possible_table_points: set[int]
    possible_result_records: set[GroupResultRecord]

    @property
    def best_table_points(self) -> int | None:
        if not self.possible_table_points:
            return None
        return max(self.possible_table_points)

    @property
    def worst_table_points(self) -> int | None:
        if not self.possible_table_points:
            return None
        return min(self.possible_table_points)


@dataclass
class TeamOutcomeEnvelope:
    possible_positions: set[int]
    best_third_place_points: int | None
    worst_third_place_points: int | None
    position_outcomes: dict[int, PositionOutcomeEnvelope]

    def outcome_for_position(self, position: int) -> PositionOutcomeEnvelope | None:
        """Return compact scenario information for a reachable position."""

        return self.position_outcomes.get(position)


@dataclass
class GroupOutcomeEnvelope:
    team_outcomes: dict[int, TeamOutcomeEnvelope]
    max_third_place_points: int
    min_third_place_points: int | None


@dataclass
class MathematicalStatus:
    qualified: bool
    eliminated: bool
    guaranteed_position: int | None


@dataclass
class _ScenarioStanding:
    team: NationalTeam
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0


@dataclass(frozen=True)
class _ScenarioMatchResult:
    home_team_id: int
    away_team_id: int
    is_exact_score: bool
    home_score: int | None = None
    away_score: int | None = None
    outcome: str | None = None


@dataclass
class _ScenarioHeadToHeadStanding:
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0


POINTS_PER_RESULT = {
    "home": (3, 0),
    "draw": (1, 1),
    "away": (0, 3),
}


def compute_mathematical_status(tournament):
    if _all_group_stage_matches_complete(tournament):
        return _compute_final_group_stage_status(tournament)

    envelopes = {
        group: _compute_group_outcome_envelope(tournament, group)
        for group in _groups_for_tournament(tournament)
    }

    group_completion = {
        group: _group_is_complete(tournament, group)
        for group in envelopes
    }

    # For completed groups, first/second/fourth are no longer mathematical
    # projections: the standings table has the real placement after applying
    # the app's normal ranking rules. Third place can still depend on the
    # cross-group third-place comparison.
    actual_positions_by_group = _actual_positions_by_group(tournament)

    max_third_thresholds = {
        group: envelope.max_third_place_points
        for group, envelope in envelopes.items()
    }

    # This is deliberately the opposite bound from max_third_thresholds.
    # For elimination, we need to know whether other groups are guaranteed to
    # produce a third-place team above this team's best possible third-place
    # points. A group's maximum third-place total is only something that could
    # happen, not something that must happen, so using max here is too
    # aggressive.
    min_third_thresholds = {
        group: envelope.min_third_place_points
        for group, envelope in envelopes.items()
    }

    status = {}

    for group, envelope in envelopes.items():
        for team_id, outcome in envelope.team_outcomes.items():
            qualified = False
            eliminated = False
            guaranteed_position = None

            if group_completion[group]:
                actual_position = actual_positions_by_group.get(group, {}).get(team_id)

                if actual_position == 1:
                    qualified = True
                    guaranteed_position = 1
                elif actual_position == 2:
                    qualified = True
                    guaranteed_position = 2
                elif actual_position == 4:
                    eliminated = True
                elif actual_position == 3:
                    if _third_place_points_guarantee_qualification(
                        group=group,
                        third_place_points=outcome.worst_third_place_points,
                        max_third_thresholds=max_third_thresholds,
                    ):
                        qualified = True
                        guaranteed_position = 3
                    elif _third_place_points_guarantee_elimination(
                        group=group,
                        third_place_points=outcome.best_third_place_points,
                        min_third_thresholds=min_third_thresholds,
                    ):
                        eliminated = True

            else:
                possible_positions = outcome.possible_positions

                # Guaranteed direct qualification from the group.
                if possible_positions.issubset({1, 2}):
                    qualified = True

                    if possible_positions == {1}:
                        guaranteed_position = 1
                    elif possible_positions == {2}:
                        guaranteed_position = 2

                # No top-two path. A team that can still finish third must not
                # be eliminated unless enough other groups are guaranteed to
                # have better third-place teams.
                elif possible_positions == {4}:
                    eliminated = True

                elif 3 in possible_positions:
                    can_still_finish_fourth = 4 in possible_positions

                    if (
                        not can_still_finish_fourth
                        and _third_place_points_guarantee_qualification(
                            group=group,
                            third_place_points=outcome.worst_third_place_points,
                            max_third_thresholds=max_third_thresholds,
                        )
                    ):
                        qualified = True

                        if possible_positions == {3}:
                            guaranteed_position = 3

                    elif _third_place_points_guarantee_elimination(
                        group=group,
                        third_place_points=outcome.best_third_place_points,
                        min_third_thresholds=min_third_thresholds,
                    ):
                        eliminated = True

            status[team_id] = MathematicalStatus(
                qualified=qualified,
                eliminated=eliminated,
                guaranteed_position=guaranteed_position,
            )

    return status


def _compute_final_group_stage_status(tournament) -> dict[int, MathematicalStatus]:
    """Return final Q/E status once every group-stage match is complete.

    Before group play is complete, third-place status must stay conservative
    because points-only math cannot safely resolve tied third-place teams. Once
    every group-stage match is complete, the app should use its real standings
    and third-place ranking tiebreakers, because the knockout bracket must be
    fully known.
    """
    from tournaments.qualification import compute_qualification

    qualification = compute_qualification(tournament)

    status = {}

    qualified_slots_by_team_id = {
        team.id: slot
        for slot, team in qualification.slot_map.items()
        if team is not None
    }

    teams = NationalTeam.objects.filter(tournament=tournament).exclude(group="")

    for team in teams:
        slot = qualified_slots_by_team_id.get(team.id)

        if slot is None:
            status[team.id] = MathematicalStatus(
                qualified=False,
                eliminated=True,
                guaranteed_position=None,
            )
            continue

        guaranteed_position = _position_from_qualification_slot(slot)

        status[team.id] = MathematicalStatus(
            qualified=True,
            eliminated=False,
            guaranteed_position=guaranteed_position,
        )

    return status


def _position_from_qualification_slot(slot: str) -> int | None:
    if not slot:
        return None

    try:
        position = int(slot[0])
    except ValueError:
        return None

    if position in {1, 2, 3}:
        return position

    return None


def compute_guaranteed_group_slot_map(tournament) -> dict[str, NationalTeam]:
    """Return known direct group slots such as ``1A`` and ``2B``.

    This is intentionally limited to direct first/second-place slots. Third-
    place bracket allocation depends on the full set of qualified third-place
    teams and should remain unresolved until it is actually known.
    """
    mathematical_status_map = compute_mathematical_status(tournament)

    slot_map = {}

    teams = NationalTeam.objects.filter(tournament=tournament).exclude(group="")

    for team in teams:
        team_status = mathematical_status_map.get(team.id)

        if team_status is None:
            continue

        if team_status.guaranteed_position in {1, 2}:
            slot_map[f"{team_status.guaranteed_position}{team.group}"] = team

    return slot_map


def _compute_group_outcome_envelope(tournament, group: str) -> GroupOutcomeEnvelope:
    teams = list(
        NationalTeam.objects.filter(
            tournament=tournament,
            group=group,
        ).order_by("name")
    )

    teams_by_id = {
        team.id: team
        for team in teams
    }
    team_ids = list(teams_by_id.keys())

    matches = list(
        Match.objects.filter(
            tournament=tournament,
            stage=Match.Stage.GROUP,
            group=group,
        )
        .select_related("home_team", "away_team")
        .order_by("match_number")
    )

    base_rows = {
        team_id: _ScenarioStanding(team=team)
        for team_id, team in teams_by_id.items()
    }

    exact_results = []
    remaining_matches = []

    for match in matches:
        if match.is_complete:
            _apply_completed_match_to_scenario_rows(base_rows, match)
            exact_results.append(_exact_result_from_match(match))
        else:
            remaining_matches.append(match)

    possible_positions = {
        team_id: set()
        for team_id in team_ids
    }

    best_third_place_points = {
        team_id: None
        for team_id in team_ids
    }

    worst_third_place_points = {
        team_id: None
        for team_id in team_ids
    }

    position_table_points = {
        team_id: {
            position: set()
            for position in (1, 2, 3, 4)
        }
        for team_id in team_ids
    }

    position_result_records = {
        team_id: {
            position: set()
            for position in (1, 2, 3, 4)
        }
        for team_id in team_ids
    }

    max_third_place_points = 0
    min_third_place_points = None

    outcomes_iterator = product(
        ("home", "draw", "away"),
        repeat=len(remaining_matches),
    )

    for outcomes in outcomes_iterator:
        scenario_points = {
            team_id: row.points
            for team_id, row in base_rows.items()
        }
        scenario_records = {
            team_id: GroupResultRecord()
            for team_id in team_ids
        }
        scenario_results = list(exact_results)

        for match, outcome in zip(remaining_matches, outcomes):
            home_points, away_points = POINTS_PER_RESULT[outcome]

            scenario_points[match.home_team_id] += home_points
            scenario_points[match.away_team_id] += away_points

            scenario_records[match.home_team_id] = _updated_record_for_outcome(
                scenario_records[match.home_team_id],
                home_points,
            )
            scenario_records[match.away_team_id] = _updated_record_for_outcome(
                scenario_records[match.away_team_id],
                away_points,
            )

            scenario_results.append(
                _ScenarioMatchResult(
                    home_team_id=match.home_team_id,
                    away_team_id=match.away_team_id,
                    is_exact_score=False,
                    outcome=outcome,
                )
            )

        scenario_rows = []
        for team_id, base_row in base_rows.items():
            scenario_rows.append(
                _ScenarioStanding(
                    team=base_row.team,
                    points=scenario_points[team_id],
                    goals_for=base_row.goals_for,
                    goals_against=base_row.goals_against,
                    goal_difference=base_row.goal_difference,
                )
            )

        scenario_positions = _possible_positions_for_scenario(
            rows=scenario_rows,
            results=scenario_results,
        )

        scenario_third_points = []

        for team_id, positions in scenario_positions.items():
            possible_positions[team_id].update(positions)

            for position in positions:
                position_table_points[team_id][position].add(scenario_points[team_id])
                position_result_records[team_id][position].add(scenario_records[team_id])

            if 3 in positions:
                points = scenario_points[team_id]
                scenario_third_points.append(points)

                current_best = best_third_place_points[team_id]
                if current_best is None or points > current_best:
                    best_third_place_points[team_id] = points

                current_worst = worst_third_place_points[team_id]
                if current_worst is None or points < current_worst:
                    worst_third_place_points[team_id] = points

        if scenario_third_points:
            scenario_max_third = max(scenario_third_points)
            scenario_min_third = min(scenario_third_points)

            if scenario_max_third > max_third_place_points:
                max_third_place_points = scenario_max_third

            if min_third_place_points is None or scenario_min_third < min_third_place_points:
                min_third_place_points = scenario_min_third

    return GroupOutcomeEnvelope(
        team_outcomes={
            team_id: TeamOutcomeEnvelope(
                possible_positions=possible_positions[team_id],
                best_third_place_points=best_third_place_points[team_id],
                worst_third_place_points=worst_third_place_points[team_id],
                position_outcomes={
                    position: PositionOutcomeEnvelope(
                        position=position,
                        possible_table_points=position_table_points[team_id][position],
                        possible_result_records=position_result_records[team_id][position],
                    )
                    for position in sorted(possible_positions[team_id])
                },
            )
            for team_id in team_ids
        },
        max_third_place_points=max_third_place_points,
        min_third_place_points=min_third_place_points,
    )


def _possible_positions_for_scenario(
    *,
    rows: list[_ScenarioStanding],
    results: list[_ScenarioMatchResult],
) -> dict[int, set[int]]:
    """Return conservative positions for one W/D/L scenario.

    Remaining group matches are simulated as win/draw/loss outcomes, but their
    exact scorelines are still unknown. The ranking therefore applies only the
    tiebreakers that are safely known for this scenario:

    * points are always known;
    * head-to-head points are known from W/D/L outcomes;
    * head-to-head goal difference/goals and overall goal difference/goals are
      used only when the relevant matches already have exact scores.

    If a future scoreline could still change an unresolved tiebreaker, every
    team in that unresolved block keeps every position in that block. That keeps
    early mathematical qualification/elimination conservative while still
    allowing completed head-to-head results to lock first/second/fourth places.
    """

    ordered_blocks = _rank_scenario_into_position_blocks(rows=rows, results=results)
    positions_by_team_id = {
        row.team.id: set()
        for row in rows
    }

    current_position = 1
    for block in ordered_blocks:
        block_positions = set(
            range(
                current_position,
                current_position + len(block),
            )
        )

        for row in block:
            positions_by_team_id[row.team.id].update(block_positions)

        current_position += len(block)

    return positions_by_team_id


def _rank_scenario_into_position_blocks(
    *,
    rows: list[_ScenarioStanding],
    results: list[_ScenarioMatchResult],
) -> list[list[_ScenarioStanding]]:
    rows_by_points: dict[int, list[_ScenarioStanding]] = defaultdict(list)

    for row in rows:
        rows_by_points[row.points].append(row)

    ordered_blocks: list[list[_ScenarioStanding]] = []
    for points in sorted(rows_by_points.keys(), reverse=True):
        ordered_blocks.extend(
            _break_scenario_tie(
                rows=rows_by_points[points],
                results=results,
                criteria=(
                    "h2h_points",
                    "h2h_goal_difference",
                    "h2h_goals_for",
                    "goal_difference",
                    "goals_for",
                    "fifa_rank",
                    "name",
                ),
            )
        )

    return ordered_blocks


def _break_scenario_tie(
    *,
    rows: list[_ScenarioStanding],
    results: list[_ScenarioMatchResult],
    criteria: tuple[str, ...],
) -> list[list[_ScenarioStanding]]:
    if len(rows) <= 1:
        return [rows]

    if not criteria:
        return [rows]

    criterion = criteria[0]
    rows_by_value = _group_scenario_rows_by_known_criterion(
        rows=rows,
        results=results,
        criterion=criterion,
    )

    # A None return means this criterion depends on unknown future scorelines.
    # Because FIFA would evaluate this criterion before all later criteria, it
    # is not safe to fall through to goal difference/FIFA rank/name.
    if rows_by_value is None:
        return [rows]

    ordered_blocks: list[list[_ScenarioStanding]] = []
    for value in sorted(rows_by_value.keys(), reverse=True):
        ordered_blocks.extend(
            _break_scenario_tie(
                rows=rows_by_value[value],
                results=results,
                criteria=criteria[1:],
            )
        )

    return ordered_blocks


def _group_scenario_rows_by_known_criterion(
    *,
    rows: list[_ScenarioStanding],
    results: list[_ScenarioMatchResult],
    criterion: str,
) -> dict[int | str, list[_ScenarioStanding]] | None:
    grouped: dict[int | str, list[_ScenarioStanding]] = defaultdict(list)

    head_to_head = None
    if criterion.startswith("h2h_"):
        if criterion in {"h2h_goal_difference", "h2h_goals_for"} and not _head_to_head_scores_are_known(rows, results):
            return None
        head_to_head = _compute_scenario_head_to_head_standings(rows, results)

    if criterion in {"goal_difference", "goals_for"} and not _overall_scores_are_known(rows, results):
        return None

    for row in rows:
        if criterion == "h2h_points":
            value = head_to_head[row.team.id].points
        elif criterion == "h2h_goal_difference":
            value = head_to_head[row.team.id].goal_difference
        elif criterion == "h2h_goals_for":
            value = head_to_head[row.team.id].goals_for
        elif criterion == "goal_difference":
            value = row.goal_difference
        elif criterion == "goals_for":
            value = row.goals_for
        elif criterion == "fifa_rank":
            # Lower FIFA rank is better, but blocks are sorted descending.
            value = -(row.team.fifa_rank or 10_000)
        elif criterion == "name":
            # Name fallback is only an app-level deterministic fallback. It is
            # reached only after all earlier tracked criteria were known/tied.
            value = _reverse_sortable_string(row.team.name)
        else:
            raise ValueError(f"Unknown mathematical-status tiebreaker: {criterion}")

        grouped[value].append(row)

    return grouped


def _compute_scenario_head_to_head_standings(
    rows: list[_ScenarioStanding],
    results: list[_ScenarioMatchResult],
) -> dict[int, _ScenarioHeadToHeadStanding]:
    team_ids = {row.team.id for row in rows}
    head_to_head = {
        team_id: _ScenarioHeadToHeadStanding()
        for team_id in team_ids
    }

    for result in results:
        if result.home_team_id not in team_ids or result.away_team_id not in team_ids:
            continue

        home = head_to_head[result.home_team_id]
        away = head_to_head[result.away_team_id]

        home_points, away_points = _points_for_scenario_result(result)
        home.points += home_points
        away.points += away_points

        if not result.is_exact_score:
            continue

        home_score = result.home_score
        away_score = result.away_score

        home.goals_for += home_score
        home.goals_against += away_score
        home.goal_difference += home_score - away_score

        away.goals_for += away_score
        away.goals_against += home_score
        away.goal_difference += away_score - home_score

    return head_to_head


def _points_for_scenario_result(result: _ScenarioMatchResult) -> tuple[int, int]:
    if result.is_exact_score:
        if result.home_score > result.away_score:
            return 3, 0
        if result.away_score > result.home_score:
            return 0, 3
        return 1, 1

    return POINTS_PER_RESULT[result.outcome]


def _head_to_head_scores_are_known(
    rows: list[_ScenarioStanding],
    results: list[_ScenarioMatchResult],
) -> bool:
    team_ids = {row.team.id for row in rows}

    for result in results:
        if result.home_team_id in team_ids and result.away_team_id in team_ids:
            if not result.is_exact_score:
                return False

    return True


def _overall_scores_are_known(
    rows: list[_ScenarioStanding],
    results: list[_ScenarioMatchResult],
) -> bool:
    team_ids = {row.team.id for row in rows}

    for result in results:
        if result.home_team_id in team_ids or result.away_team_id in team_ids:
            if not result.is_exact_score:
                return False

    return True


def _exact_result_from_match(match: Match) -> _ScenarioMatchResult:
    return _ScenarioMatchResult(
        home_team_id=match.home_team_id,
        away_team_id=match.away_team_id,
        is_exact_score=True,
        home_score=match.home_score,
        away_score=match.away_score,
    )


def _apply_completed_match_to_scenario_rows(
    rows_by_team_id: dict[int, _ScenarioStanding],
    match: Match,
) -> None:
    home = rows_by_team_id[match.home_team_id]
    away = rows_by_team_id[match.away_team_id]
    home_score = match.home_score
    away_score = match.away_score

    home.goals_for += home_score
    home.goals_against += away_score
    home.goal_difference += home_score - away_score

    away.goals_for += away_score
    away.goals_against += home_score
    away.goal_difference += away_score - home_score

    if home_score > away_score:
        home.points += 3
    elif away_score > home_score:
        away.points += 3
    else:
        home.points += 1
        away.points += 1


def _reverse_sortable_string(value: str) -> str:
    """Return a string whose descending sort mirrors normal ascending sort."""

    return "".join(chr(0x10FFFF - ord(char)) for char in value)


def _actual_positions_by_group(tournament) -> dict[str, dict[int, int]]:
    standings_by_group = compute_group_standings(tournament)

    return {
        group: {
            row.team.id: row.position
            for row in standings
            if row.position is not None
        }
        for group, standings in standings_by_group.items()
    }


def _third_place_points_guarantee_qualification(
    *,
    group: str,
    third_place_points: int | None,
    max_third_thresholds: dict[str, int],
) -> bool:
    if third_place_points is None:
        return False

    lower_groups = 0

    for other_group, threshold in max_third_thresholds.items():
        if other_group == group:
            continue

        if third_place_points > threshold:
            lower_groups += 1

    return lower_groups >= 4


def _third_place_points_guarantee_elimination(
    *,
    group: str,
    third_place_points: int | None,
    min_third_thresholds: dict[str, int | None],
) -> bool:
    if third_place_points is None:
        return True

    higher_groups = 0

    for other_group, threshold in min_third_thresholds.items():
        if other_group == group:
            continue

        if threshold is None:
            continue

        if third_place_points < threshold:
            higher_groups += 1

    return higher_groups >= 8


def _updated_record_for_outcome(
    record: GroupResultRecord,
    table_points: int,
) -> GroupResultRecord:
    """Return a new W/D/L record after one remaining group result."""

    if table_points == 3:
        return GroupResultRecord(
            wins=record.wins + 1,
            draws=record.draws,
            losses=record.losses,
        )

    if table_points == 1:
        return GroupResultRecord(
            wins=record.wins,
            draws=record.draws + 1,
            losses=record.losses,
        )

    return GroupResultRecord(
        wins=record.wins,
        draws=record.draws,
        losses=record.losses + 1,
    )


def _apply_completed_match(points: dict[int, int], match: Match) -> None:
    if match.home_score > match.away_score:
        points[match.home_team_id] += 3
    elif match.away_score > match.home_score:
        points[match.away_team_id] += 3
    else:
        points[match.home_team_id] += 1
        points[match.away_team_id] += 1


def _groups_for_tournament(tournament) -> list[str]:
    return list(
        NationalTeam.objects.filter(tournament=tournament)
        .exclude(group="")
        .values_list("group", flat=True)
        .distinct()
        .order_by("group")
    )


def _group_is_complete(tournament, group: str) -> bool:
    matches = Match.objects.filter(
        tournament=tournament,
        stage=Match.Stage.GROUP,
        group=group,
    )

    if not matches.exists():
        return False

    return all(match.is_complete for match in matches)


def _all_group_stage_matches_complete(tournament) -> bool:
    matches = Match.objects.filter(
        tournament=tournament,
        stage=Match.Stage.GROUP,
    )

    if not matches.exists():
        return False

    return all(match.is_complete for match in matches)
