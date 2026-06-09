from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from leagues.models import League, LeagueMember
from tournaments.models import Match, NationalTeam, TeamTournamentStatus

from .models import StandingEntry
from scoring.defaults import default_scoring_config, default_tiebreaker_config


GROUP_STAGE = Match.Stage.GROUP

FINISH_RANKS = {
    "champion": 1,
    "runner_up": 2,
    "third_place": 3,
    "fourth_place": 4,
}


@transaction.atomic
def recompute_league_standings(league: League) -> list[StandingEntry]:
    StandingEntry.objects.filter(league=league).delete()

    entries = []

    for member in league.members.all():
        stats = _compute_member_stats(league, member)

        entries.append(
            StandingEntry(
                league=league,
                member=member,
                points=stats["points"],
                wins=stats["wins"],
                draws=stats["draws"],
                losses=stats["losses"],
                teams_advanced=stats["teams_advanced"],
                best_finish_rank=stats["best_finish_rank"],
                goal_difference=stats["goal_difference"],
                goals_scored=stats["goals_scored"],
            )
        )

    entries.sort(key=lambda entry: _standing_sort_key(entry, league))

    for rank, entry in enumerate(entries, start=1):
        entry.current_rank = rank

    return StandingEntry.objects.bulk_create(entries)


def refresh_leagues_after_tournament_change(
    tournament,
    *,
    reason: str = "Tournament state changed.",
) -> list[dict]:
    """Refresh league scoring caches after a tournament-level change.

    A match result belongs to the tournament, not to one specific league.
    Therefore every league using that tournament needs fresh standings and a
    projection refresh request. Projection recomputation is queued through the
    public background-job API so callers do not need to know about Redis.

    Returns a small list of per-league results for UI messages or logs.
    """
    from scoring.jobs import ProjectionQueueUnavailable, request_projection_recompute

    results = []

    leagues = League.objects.filter(tournament=tournament).order_by("slug")

    for league in leagues:
        recompute_league_standings(league)

        try:
            queue_result = request_projection_recompute(league, reason=reason)
        except ProjectionQueueUnavailable as exc:
            results.append(
                {
                    "league": league,
                    "queued": False,
                    "status": "unavailable",
                    "message": str(exc),
                }
            )
        else:
            results.append(
                {
                    "league": league,
                    "queued": queue_result.queued,
                    "status": queue_result.status,
                    "message": queue_result.message,
                }
            )

    return results


def reset_league_scoring_state(
    league: League,
    *,
    projection_reason: str = "Team assignments were reset.",
) -> dict[str, int]:
    """Clear cached standings/projections for a league with no assignments.

    Assignment reset is different from a normal assignment edit: once every
    assignment is deleted, standings and projections are no longer meaningful.
    Therefore we remove cached rows instead of recomputing placeholder standings
    or leaving stale projection values visible.

    Returns a small summary of deleted rows for tests/logs.
    """
    from scoring.models import ProjectionEntry, ProjectionJobState

    standings_deleted, _ = StandingEntry.objects.filter(league=league).delete()
    projections_deleted, _ = ProjectionEntry.objects.filter(league=league).delete()

    job_state, _ = ProjectionJobState.objects.get_or_create(league=league)
    job_state.status = ProjectionJobState.Status.IDLE
    job_state.last_job_id = ""
    job_state.requested_at = None
    job_state.started_at = None
    job_state.finished_at = None
    job_state.last_heartbeat_at = None
    job_state.error_message = projection_reason[:500]
    job_state.save(
        update_fields=[
            "status",
            "last_job_id",
            "requested_at",
            "started_at",
            "finished_at",
            "last_heartbeat_at",
            "error_message",
            "updated_at",
        ]
    )

    return {
        "standings_deleted": standings_deleted,
        "projections_deleted": projections_deleted,
    }




def compute_team_contribution(league: League, team: NationalTeam) -> dict:
    """Return the current fantasy contribution for one national team.

    This mirrors the same scoring logic used by league standings, but isolates
    the contribution of a single assigned team so it can be displayed on the
    league dashboard.
    """
    stats = _empty_member_stats()
    _add_team_stats(league, team, stats)
    return stats


def team_is_eliminated_from_scoring(league: League, team: NationalTeam) -> bool:
    """Return whether a team can no longer add future fantasy points.

    Group-stage mathematical elimination is handled through
    TeamTournamentStatus. Knockout elimination is detected directly from
    completed knockout matches, because the status table only stores final
    tournament ranks for the final and third-place match.
    """
    try:
        status = team.tournament_status
    except TeamTournamentStatus.DoesNotExist:
        status = None

    if status is not None:
        if status.finish_rank is not None:
            return status.finish_rank != FINISH_RANKS["champion"]

        if status.mathematically_eliminated and not status.advanced_from_group:
            return True

    completed_knockout_loss_exists = Match.objects.filter(
        tournament=league.tournament,
        status=Match.Status.FINAL,
        winner__isnull=False,
    ).exclude(
        stage=Match.Stage.GROUP,
    ).filter(
        Q(home_team=team) | Q(away_team=team),
    ).exclude(
        winner=team,
    ).exists()

    return completed_knockout_loss_exists


def _empty_member_stats() -> dict:
    return {
        "points": Decimal("0"),
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "teams_advanced": 0,
        "best_finish_rank": None,
        "goal_difference": 0,
        "goals_scored": 0,
    }

def _compute_member_stats(league: League, member: LeagueMember) -> dict:
    teams = list(
        NationalTeam.objects.filter(
            fantasy_assignments__league=league,
            fantasy_assignments__member=member,
        )
    )

    stats = _empty_member_stats()

    for team in teams:
        _add_team_stats(league, team, stats)

    return stats


def _add_team_stats(league: League, team: NationalTeam, stats: dict) -> None:
    config = _scoring_config(league)

    matches = (
        Match.objects.filter(tournament=league.tournament, home_team=team)
        | Match.objects.filter(tournament=league.tournament, away_team=team)
    )

    _add_status_points(league, team, config, stats)

    for match in matches.distinct():
        if not match.is_complete:
            continue

        team_score, opponent_score = _score_for_team(match, team)

        stats["goals_scored"] += team_score
        stats["goal_difference"] += team_score - opponent_score

        if match.stage == GROUP_STAGE:
            _add_group_points(config, team_score, opponent_score, stats)
        else:
            did_advance = _add_knockout_points(
                config,
                match,
                team,
                stats,
            )


def _add_group_points(
    config: dict,
    team_score: int,
    opponent_score: int,
    stats: dict,
) -> None:
    if team_score > opponent_score:
        stats["points"] += Decimal(str(config["group_win"]))
        stats["wins"] += 1
    elif team_score == opponent_score:
        stats["points"] += Decimal(str(config["group_draw"]))
        stats["draws"] += 1
    else:
        stats["points"] += Decimal(str(config["group_loss"]))
        stats["losses"] += 1


def _add_knockout_points(
    config: dict,
    match: Match,
    team: NationalTeam,
    stats: dict,
) -> bool:
    did_win = match.winner_id == team.id

    if did_win:
        stats["wins"] += 1

        if match.went_to_penalties:
            stats["points"] += Decimal(str(config["knockout_win_penalties"]))
        elif match.went_to_extra_time:
            stats["points"] += Decimal(str(config["knockout_win_extra_time"]))
        else:
            stats["points"] += Decimal(str(config["knockout_win_regulation"]))

        return True

    stats["losses"] += 1

    if match.went_to_penalties:
        stats["points"] += Decimal(str(config["knockout_loss_penalties"]))
    elif match.went_to_extra_time:
        stats["points"] += Decimal(str(config["knockout_loss_extra_time"]))

    return False


def _add_status_points(
    league: League,
    team: NationalTeam,
    config: dict,
    stats: dict,
) -> None:
    try:
        status = team.tournament_status
    except TeamTournamentStatus.DoesNotExist:
        return

    if status.advanced_from_group:
        stats["points"] += Decimal(str(config["qualify_knockout"]))
        stats["teams_advanced"] += 1

    if status.finish_rank is not None:
        _add_finish_bonus(config, status.finish_rank, stats)
        _update_best_finish(status.finish_rank, stats)


def _add_finish_bonus(config: dict, finish_rank: int, stats: dict) -> None:
    if finish_rank == FINISH_RANKS["champion"]:
        stats["points"] += Decimal(str(config["champion_bonus"]))
    elif finish_rank == FINISH_RANKS["runner_up"]:
        stats["points"] += Decimal(str(config["runner_up_bonus"]))
    elif finish_rank == FINISH_RANKS["third_place"]:
        stats["points"] += Decimal(str(config["third_place_bonus"]))
    elif finish_rank == FINISH_RANKS["fourth_place"]:
        stats["points"] += Decimal(str(config["fourth_place_bonus"]))


def _update_best_finish(finish_rank: int, stats: dict) -> None:
    current = stats["best_finish_rank"]

    if current is None or finish_rank < current:
        stats["best_finish_rank"] = finish_rank


def _score_for_team(match: Match, team: NationalTeam) -> tuple[int, int]:
    if match.home_team_id == team.id:
        return match.home_score, match.away_score

    return match.away_score, match.home_score


def _scoring_config(league: League) -> dict:
    return default_scoring_config() | league.scoring_config

def _standing_sort_key(entry: StandingEntry, league: League) -> tuple:
    sort_key = [-entry.points]

    tiebreakers = league.tiebreaker_config or default_tiebreaker_config()

    for tiebreaker in tiebreakers:
        sort_key.append(_tiebreaker_sort_value(entry, tiebreaker))

    sort_key.append(entry.member.display_name.lower())

    return tuple(sort_key)


def _tiebreaker_sort_value(entry: StandingEntry, tiebreaker: str):
    if tiebreaker == "teams_advanced":
        return -entry.teams_advanced

    if tiebreaker == "wins":
        return -entry.wins

    if tiebreaker == "goal_difference":
        return -entry.goal_difference

    if tiebreaker == "goals_scored":
        return -entry.goals_scored

    if tiebreaker == "best_finish_rank":
        return entry.best_finish_rank or 999

    return 0