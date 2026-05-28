# `tournaments/mathematical_status.py`
from dataclasses import dataclass
from itertools import product

from tournaments.models import Match, NationalTeam
from tournaments.standings import compute_group_standings


@dataclass
class TeamOutcomeEnvelope:
    possible_positions: set[int]
    best_third_place_points: int | None
    worst_third_place_points: int | None


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

    team_ids = [team.id for team in teams]

    matches = list(
        Match.objects.filter(
            tournament=tournament,
            stage=Match.Stage.GROUP,
            group=group,
        )
        .select_related("home_team", "away_team")
        .order_by("match_number")
    )

    base_points = {
        team_id: 0
        for team_id in team_ids
    }

    remaining_matches = []

    for match in matches:
        if match.is_complete:
            _apply_completed_match(base_points, match)
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

    max_third_place_points = 0
    min_third_place_points = None

    outcomes_iterator = product(
        ("home", "draw", "away"),
        repeat=len(remaining_matches),
    )

    for outcomes in outcomes_iterator:
        scenario_points = dict(base_points)

        for match, outcome in zip(remaining_matches, outcomes):
            home_points, away_points = POINTS_PER_RESULT[outcome]

            scenario_points[match.home_team_id] += home_points
            scenario_points[match.away_team_id] += away_points

        scenario_positions = _possible_positions_by_points_only(scenario_points)

        scenario_third_points = []

        for team_id, positions in scenario_positions.items():
            possible_positions[team_id].update(positions)

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
            )
            for team_id in team_ids
        },
        max_third_place_points=max_third_place_points,
        min_third_place_points=min_third_place_points,
    )


def _possible_positions_by_points_only(points: dict[int, int]) -> dict[int, set[int]]:
    """
    Return conservative possible finishing positions from points only.

    This intentionally does not break ties. If two teams are tied for first,
    both can occupy first or second. If three teams are tied for first, all
    three can occupy first, second, or third.
    """
    grouped = {}

    for team_id, team_points in points.items():
        grouped.setdefault(team_points, set()).add(team_id)

    ordered_points = sorted(grouped.keys(), reverse=True)

    positions_by_team = {
        team_id: set()
        for team_id in points
    }

    current_position = 1

    for team_points in ordered_points:
        tied_team_ids = grouped[team_points]
        tied_positions = set(
            range(
                current_position,
                current_position + len(tied_team_ids),
            )
        )

        for team_id in tied_team_ids:
            positions_by_team[team_id].update(tied_positions)

        current_position += len(tied_team_ids)

    return positions_by_team


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
