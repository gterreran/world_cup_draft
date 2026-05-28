from tournaments.models import Match, NationalTeam, TeamTournamentStatus


FINISH_RANKS = {
    Match.Stage.FINAL: {
        "winner": 1,
        "loser": 2,
    },
    Match.Stage.THIRD_PLACE: {
        "winner": 3,
        "loser": 4,
    },
}


def recompute_team_statuses(tournament, qualification_result) -> None:
    TeamTournamentStatus.objects.filter(
        team__tournament=tournament
    ).delete()

    qualified_team_ids = set()

    for team in qualification_result.slot_map.values():
        qualified_team_ids.add(team.id)

    all_teams = NationalTeam.objects.filter(
        tournament=tournament,
    )

    status_map = {}

    for team in all_teams:
        status_map[team.id] = TeamTournamentStatus.objects.create(
            tournament=tournament,
            team=team,
            advanced_from_group=team.id in qualified_team_ids,
        )

    knockout_matches = (
        Match.objects.filter(tournament=tournament)
        .exclude(stage=Match.Stage.GROUP)
        .select_related(
            "home_team",
            "away_team",
            "winner",
        )
    )

    for match in knockout_matches:
        _apply_knockout_status(match, status_map)


def _apply_knockout_status(match, status_map):
    if not match.is_complete:
        return

    if not match.winner_id:
        return

    loser = _loser(match)

    finish_config = FINISH_RANKS.get(match.stage)

    if finish_config:
        winner_status = status_map[match.winner_id]
        winner_status.finish_rank = finish_config["winner"]
        winner_status.save(update_fields=["finish_rank"])

        if loser:
            loser_status = status_map[loser.id]
            loser_status.finish_rank = finish_config["loser"]
            loser_status.save(update_fields=["finish_rank"])


def _loser(match):
    if not match.winner_id:
        return None

    if match.winner_id == match.home_team_id:
        return match.away_team

    return match.home_team