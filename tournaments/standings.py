from dataclasses import dataclass

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


def compute_group_standings(tournament: Tournament) -> dict[str, list[GroupStanding]]:
    standings_by_group = _initialize_group_standings(tournament)

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

    return _sort_and_rank_groups(standings_by_group)


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
    standings_by_group: dict[str, dict[int, GroupStanding]],
) -> dict[str, list[GroupStanding]]:
    ranked_groups = {}

    for group_name, standings_by_team_id in standings_by_group.items():
        standings = list(standings_by_team_id.values())

        standings.sort(
            key=lambda row: (
                -row.points,
                -row.goal_difference,
                -row.goals_for,
                row.team.name,
            )
        )

        for position, row in enumerate(standings, start=1):
            row.position = position

        ranked_groups[group_name] = standings

    return dict(sorted(ranked_groups.items()))