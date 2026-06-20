from dataclasses import dataclass
from collections import defaultdict
from typing import Iterable

from tournaments.models import Match, NationalTeam, Tournament


@dataclass
class GroupStanding:
    team: NationalTeam
    played: int = 0
    wins: int = 0
    draws: int = 0
    losses: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0
    points: int = 0
    position: int | None = None


@dataclass
class _HeadToHeadStanding:
    points: int = 0
    goals_for: int = 0
    goals_against: int = 0
    goal_difference: int = 0


def compute_group_standings(tournament: Tournament) -> dict[str, list[GroupStanding]]:
    standings_by_group = _initialize_group_standings(tournament)
    completed_matches_by_group: dict[str, list[Match]] = defaultdict(list)

    matches = (
        Match.objects.filter(tournament=tournament, stage=Match.Stage.GROUP)
        .select_related("home_team", "away_team")
        .order_by("group", "match_number")
    )

    for match in matches:
        if not match.is_complete:
            continue

        group = _group_for_match(match)

        if not group:
            continue

        if match.home_team_id not in standings_by_group[group]:
            continue

        if match.away_team_id not in standings_by_group[group]:
            continue

        _apply_match_result(
            standings_by_group[group][match.home_team_id],
            standings_by_group[group][match.away_team_id],
            match,
        )
        completed_matches_by_group[group].append(match)

    return _sort_and_rank_groups(
        standings_by_group=standings_by_group,
        completed_matches_by_group=completed_matches_by_group,
    )


def _initialize_group_standings(
    tournament: Tournament,
) -> dict[str, dict[int, GroupStanding]]:
    standings_by_group = {}

    teams = NationalTeam.objects.filter(tournament=tournament).order_by(
        "group",
        "name",
    )

    for team in teams:
        if not team.group:
            continue

        standings_by_group.setdefault(team.group, {})
        standings_by_group[team.group][team.id] = GroupStanding(team=team)

    return standings_by_group


def _group_for_match(match: Match) -> str:
    if match.group:
        return match.group

    if match.home_team and match.home_team.group:
        return match.home_team.group

    if match.away_team and match.away_team.group:
        return match.away_team.group

    return ""


def _apply_match_result(
    home: GroupStanding,
    away: GroupStanding,
    match: Match,
) -> None:
    home_score = match.home_score
    away_score = match.away_score

    home.played += 1
    away.played += 1

    home.goals_for += home_score
    home.goals_against += away_score
    home.goal_difference += home_score - away_score

    away.goals_for += away_score
    away.goals_against += home_score
    away.goal_difference += away_score - home_score

    if home_score > away_score:
        home.wins += 1
        home.points += 3
        away.losses += 1
    elif away_score > home_score:
        away.wins += 1
        away.points += 3
        home.losses += 1
    else:
        home.draws += 1
        away.draws += 1
        home.points += 1
        away.points += 1


def _sort_and_rank_groups(
    *,
    standings_by_group: dict[str, dict[int, GroupStanding]],
    completed_matches_by_group: dict[str, list[Match]],
) -> dict[str, list[GroupStanding]]:
    ranked_groups = {}

    for group_name, standings_by_team_id in standings_by_group.items():
        standings = list(standings_by_team_id.values())
        completed_matches = completed_matches_by_group.get(group_name, [])

        standings = _rank_group_standings(standings, completed_matches)

        for position, row in enumerate(standings, start=1):
            row.position = position

        ranked_groups[group_name] = standings

    return dict(sorted(ranked_groups.items()))


def _rank_group_standings(
    standings: list[GroupStanding],
    completed_matches: list[Match],
) -> list[GroupStanding]:
    """Rank one group using the 2026 FIFA group-stage tiebreaker order.

    The 2026 rules rank teams level on points by head-to-head results before
    falling back to all-group goal difference and goals scored. Fair-play/team
    conduct points are not tracked by this app yet, so FIFA ranking is the next
    available deterministic criterion before a final name fallback.
    """

    ranked: list[GroupStanding] = []
    rows_by_points: dict[int, list[GroupStanding]] = defaultdict(list)

    for row in standings:
        rows_by_points[row.points].append(row)

    for points in sorted(rows_by_points.keys(), reverse=True):
        ranked.extend(
            _break_points_tie(
                rows=rows_by_points[points],
                completed_matches=completed_matches,
                criteria=(
                    "h2h_points",
                    "h2h_goal_difference",
                    "h2h_goals_for",
                    "goal_difference",
                    "goals_for",
                    "fifa_rank",
                ),
            )
        )

    return ranked


def _break_points_tie(
    *,
    rows: list[GroupStanding],
    completed_matches: list[Match],
    criteria: tuple[str, ...],
) -> list[GroupStanding]:
    if len(rows) <= 1:
        return rows

    if not criteria:
        return sorted(rows, key=lambda row: row.team.name)

    criterion = criteria[0]
    rows_by_value = _group_rows_by_criterion(
        rows=rows,
        completed_matches=completed_matches,
        criterion=criterion,
    )

    ranked: list[GroupStanding] = []
    for value in sorted(rows_by_value.keys(), reverse=True):
        ranked.extend(
            _break_points_tie(
                rows=rows_by_value[value],
                completed_matches=completed_matches,
                criteria=criteria[1:],
            )
        )

    return ranked


def _group_rows_by_criterion(
    *,
    rows: list[GroupStanding],
    completed_matches: list[Match],
    criterion: str,
) -> dict[int, list[GroupStanding]]:
    grouped: dict[int, list[GroupStanding]] = defaultdict(list)

    head_to_head = None
    if criterion.startswith("h2h_"):
        head_to_head = _compute_head_to_head_standings(rows, completed_matches)

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
            # Lower FIFA rank is better, but this function sorts descending.
            value = -(row.team.fifa_rank or 10_000)
        else:
            raise ValueError(f"Unknown group standings tiebreaker: {criterion}")

        grouped[value].append(row)

    return grouped


def _compute_head_to_head_standings(
    rows: Iterable[GroupStanding],
    completed_matches: list[Match],
) -> dict[int, _HeadToHeadStanding]:
    team_ids = {row.team.id for row in rows}
    head_to_head = {
        team_id: _HeadToHeadStanding()
        for team_id in team_ids
    }

    for match in completed_matches:
        if match.home_team_id not in team_ids or match.away_team_id not in team_ids:
            continue

        home = head_to_head[match.home_team_id]
        away = head_to_head[match.away_team_id]
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

    return head_to_head
