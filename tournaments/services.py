from collections import defaultdict

from tournaments.models import Match, NationalTeam


def build_group_stage_context(tournament):
    groups = {}

    teams = NationalTeam.objects.filter(tournament=tournament).order_by("group", "name")

    for team in teams:
        if not team.group:
            continue

        groups.setdefault(team.group, {
            "teams": {},
            "matches": [],
        })

        groups[team.group]["teams"][team.id] = {
            "team": team,
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "goals_for": 0,
            "goals_against": 0,
            "goal_difference": 0,
            "points": 0,
        }

    matches = (
        Match.objects.filter(tournament=tournament, stage=Match.Stage.GROUP)
        .select_related("home_team", "away_team")
        .order_by("group", "kickoff_time", "match_number")
    )

    for match in matches:
        group = match.group or (
            match.home_team.group if match.home_team else ""
        )

        if not group:
            continue

        groups.setdefault(group, {
            "teams": {},
            "matches": [],
        })

        groups[group]["matches"].append(match)

        if not match.is_complete:
            continue

        _apply_group_result(groups[group]["teams"], match)

    output = []

    for group_name in sorted(groups):
        standings = list(groups[group_name]["teams"].values())
        standings.sort(
            key=lambda row: (
                -row["points"],
                -row["goal_difference"],
                -row["goals_for"],
                row["team"].name,
            )
        )

        output.append({
            "name": group_name,
            "standings": standings,
            "matches": groups[group_name]["matches"],
        })

    return output


def _apply_group_result(standings, match):
    home = standings[match.home_team_id]
    away = standings[match.away_team_id]

    home_score = match.home_score
    away_score = match.away_score

    home["played"] += 1
    away["played"] += 1

    home["goals_for"] += home_score
    home["goals_against"] += away_score
    home["goal_difference"] += home_score - away_score

    away["goals_for"] += away_score
    away["goals_against"] += home_score
    away["goal_difference"] += away_score - home_score

    if home_score > away_score:
        home["wins"] += 1
        home["points"] += 3
        away["losses"] += 1
    elif home_score < away_score:
        away["wins"] += 1
        away["points"] += 3
        home["losses"] += 1
    else:
        home["draws"] += 1
        away["draws"] += 1
        home["points"] += 1
        away["points"] += 1