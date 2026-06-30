from dataclasses import dataclass
from decimal import Decimal

from django.db import transaction
from django.db.models import Q

from assignments.models import TeamAssignment
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

STAGE_ORDER = {
    Match.Stage.GROUP: 0,
    Match.Stage.ROUND_OF_32: 1,
    Match.Stage.ROUND_OF_16: 2,
    Match.Stage.QUARTERFINAL: 3,
    Match.Stage.SEMIFINAL: 4,
    Match.Stage.THIRD_PLACE: 5,
    Match.Stage.FINAL: 6,
}

FINISH_LABELS = {
    FINISH_RANKS["champion"]: "Champion",
    FINISH_RANKS["runner_up"]: "Runner-up",
    FINISH_RANKS["third_place"]: "Third place",
    FINISH_RANKS["fourth_place"]: "Fourth place",
}


@dataclass(frozen=True)
class TeamBreakdownLine:
    """One visible point source in a team scoring breakdown."""

    label: str
    description: str
    points: Decimal
    result_label: str = ""
    method_label: str = ""
    score_label: str = ""
    is_bonus: bool = False


@dataclass(frozen=True)
class TeamBreakdownSection:
    """Display-ready point sources grouped under one heading."""

    title: str
    lines: list[TeamBreakdownLine]


@dataclass(frozen=True)
class TeamPointBreakdown:
    """Display-ready fantasy scoring breakdown for one assigned team."""

    team: NationalTeam | None
    assignment: TeamAssignment
    total_points: Decimal
    wins: int
    draws: int
    losses: int
    goal_difference: int
    goals_scored: int
    teams_advanced: int
    is_eliminated: bool
    is_hidden_blank: bool
    sections: list[TeamBreakdownSection]


@dataclass(frozen=True)
class MemberPointBreakdown:
    """Display-ready fantasy scoring breakdown for one manager."""

    league: League
    member: LeagueMember
    teams: list[TeamPointBreakdown]
    total_points: Decimal



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


def compute_member_point_breakdown(
    league: League,
    member: LeagueMember,
    *,
    show_hidden: bool = False,
) -> MemberPointBreakdown:
    """Return a manager-level breakdown of fantasy points by assigned team.

    Public league pages may contain unrevealed assignments. When ``show_hidden``
    is False, unrevealed teams are represented as blank slots and do not leak
    team names or point totals. Commissioners can pass ``show_hidden=True`` to
    audit prepared-but-hidden assignments.
    """

    assignments = TeamAssignment.objects.filter(
        league=league,
        member=member,
    ).select_related(
        "national_team",
    ).order_by(
        "reveal_order",
        "national_team__pot",
        "national_team__name",
        "id",
    )

    team_breakdowns = []

    for assignment in assignments:
        if not assignment.revealed and not show_hidden:
            team_breakdowns.append(
                TeamPointBreakdown(
                    team=None,
                    assignment=assignment,
                    total_points=Decimal("0"),
                    wins=0,
                    draws=0,
                    losses=0,
                    goal_difference=0,
                    goals_scored=0,
                    teams_advanced=0,
                    is_eliminated=False,
                    is_hidden_blank=True,
                    sections=[],
                )
            )
            continue

        team_breakdowns.append(compute_team_point_breakdown(league, assignment))

    total_points = sum((team.total_points for team in team_breakdowns), Decimal("0"))

    return MemberPointBreakdown(
        league=league,
        member=member,
        teams=team_breakdowns,
        total_points=total_points,
    )


def compute_team_point_breakdown(
    league: League,
    assignment: TeamAssignment,
) -> TeamPointBreakdown:
    """Return a display-ready scoring breakdown for one assigned team."""

    config = _scoring_config(league)
    team = assignment.national_team
    stats = _empty_member_stats()
    sections_by_title: dict[str, list[TeamBreakdownLine]] = {}

    matches = _completed_matches_for_team(league, team)
    live_states_by_match_id = _live_states_by_match_id(matches)

    for match in matches:
        team_score, opponent_score = _score_for_team(match, team)
        opponent = _opponent_for_team(match, team)

        stats["goals_scored"] += team_score
        stats["goal_difference"] += team_score - opponent_score

        if match.stage == GROUP_STAGE:
            points, result_label = _group_match_points(
                config,
                team_score,
                opponent_score,
            )
            _apply_group_result_to_stats(points, result_label, stats)
            section_title = "Group stage"
            method_label = ""
        else:
            points, result_label, method_label = _knockout_match_points(
                config,
                match,
                team,
            )
            _apply_knockout_result_to_stats(points, result_label, stats)
            section_title = match.get_stage_display()

        score_label = _match_score_label(match, team, live_states_by_match_id.get(match.id))
        sections_by_title.setdefault(section_title, []).append(
            TeamBreakdownLine(
                label=_match_line_label(match),
                description=_match_line_description(opponent, score_label),
                points=points,
                result_label=result_label,
                method_label=method_label,
                score_label=score_label,
            )
        )

    _append_status_breakdown_lines(
        config=config,
        team=team,
        stats=stats,
        sections_by_title=sections_by_title,
    )

    sections = [
        TeamBreakdownSection(title=title, lines=lines)
        for title, lines in _ordered_sections(sections_by_title)
    ]

    return TeamPointBreakdown(
        team=team,
        assignment=assignment,
        total_points=stats["points"],
        wins=stats["wins"],
        draws=stats["draws"],
        losses=stats["losses"],
        goal_difference=stats["goal_difference"],
        goals_scored=stats["goals_scored"],
        teams_advanced=stats["teams_advanced"],
        is_eliminated=team_is_eliminated_from_scoring(league, team),
        is_hidden_blank=False,
        sections=sections,
    )


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
    points, result_label = _group_match_points(config, team_score, opponent_score)
    _apply_group_result_to_stats(points, result_label, stats)


def _add_knockout_points(
    config: dict,
    match: Match,
    team: NationalTeam,
    stats: dict,
) -> bool:
    points, result_label, _method_label = _knockout_match_points(config, match, team)
    _apply_knockout_result_to_stats(points, result_label, stats)
    return result_label == "W"


def _group_match_points(
    config: dict,
    team_score: int,
    opponent_score: int,
) -> tuple[Decimal, str]:
    if team_score > opponent_score:
        return Decimal(str(config["group_win"])), "W"
    if team_score == opponent_score:
        return Decimal(str(config["group_draw"])), "D"
    return Decimal(str(config["group_loss"])), "L"


def _knockout_match_points(
    config: dict,
    match: Match,
    team: NationalTeam,
) -> tuple[Decimal, str, str]:
    did_win = match.winner_id == team.id
    result_label = "W" if did_win else "L"

    if match.went_to_penalties:
        key = "knockout_win_penalties" if did_win else "knockout_loss_penalties"
        return Decimal(str(config[key])), result_label, "Penalties"

    if match.went_to_extra_time:
        key = "knockout_win_extra_time" if did_win else "knockout_loss_extra_time"
        return Decimal(str(config[key])), result_label, "Extra time"

    if did_win:
        return Decimal(str(config["knockout_win_regulation"])), result_label, "Regulation"

    # A regulation knockout loss does not have its own configurable scoring key.
    return Decimal("0"), result_label, "Regulation"


def _apply_group_result_to_stats(points: Decimal, result_label: str, stats: dict) -> None:
    stats["points"] += points
    if result_label == "W":
        stats["wins"] += 1
    elif result_label == "D":
        stats["draws"] += 1
    else:
        stats["losses"] += 1


def _apply_knockout_result_to_stats(points: Decimal, result_label: str, stats: dict) -> None:
    stats["points"] += points
    if result_label == "W":
        stats["wins"] += 1
    else:
        stats["losses"] += 1


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


def _completed_matches_for_team(league: League, team: NationalTeam) -> list[Match]:
    matches = (
        Match.objects.filter(tournament=league.tournament, home_team=team)
        | Match.objects.filter(tournament=league.tournament, away_team=team)
    )

    return list(
        matches.select_related("home_team", "away_team", "winner")
        .filter(
            status=Match.Status.FINAL,
            home_score__isnull=False,
            away_score__isnull=False,
        )
        .distinct()
        .order_by("match_date", "kickoff_time", "match_number", "id")
    )


def _live_states_by_match_id(matches: list[Match]) -> dict[int, object]:
    match_ids = [match.id for match in matches]
    if not match_ids:
        return {}

    try:
        from live_scores.models import LiveMatchState
    except ImportError:
        return {}

    return {
        live_state.match_id: live_state
        for live_state in LiveMatchState.objects.filter(match_id__in=match_ids)
    }


def _append_status_breakdown_lines(
    *,
    config: dict,
    team: NationalTeam,
    stats: dict,
    sections_by_title: dict[str, list[TeamBreakdownLine]],
) -> None:
    try:
        status = team.tournament_status
    except TeamTournamentStatus.DoesNotExist:
        return

    if status.advanced_from_group:
        points = Decimal(str(config["qualify_knockout"]))
        stats["points"] += points
        stats["teams_advanced"] += 1
        sections_by_title.setdefault("Group stage", []).append(
            TeamBreakdownLine(
                label="Qualification bonus",
                description="Advanced from group",
                points=points,
                result_label="Yes",
                is_bonus=True,
            )
        )

    if status.finish_rank is not None:
        finish_points = _finish_bonus_points(config, status.finish_rank)
        if finish_points:
            stats["points"] += finish_points
            sections_by_title.setdefault("Tournament bonus", []).append(
                TeamBreakdownLine(
                    label="Finish bonus",
                    description=FINISH_LABELS.get(
                        status.finish_rank,
                        f"Finished #{status.finish_rank}",
                    ),
                    points=finish_points,
                    result_label="Bonus",
                    is_bonus=True,
                )
            )

        _update_best_finish(status.finish_rank, stats)


def _finish_bonus_points(config: dict, finish_rank: int) -> Decimal:
    if finish_rank == FINISH_RANKS["champion"]:
        return Decimal(str(config["champion_bonus"]))
    if finish_rank == FINISH_RANKS["runner_up"]:
        return Decimal(str(config["runner_up_bonus"]))
    if finish_rank == FINISH_RANKS["third_place"]:
        return Decimal(str(config["third_place_bonus"]))
    if finish_rank == FINISH_RANKS["fourth_place"]:
        return Decimal(str(config["fourth_place_bonus"]))
    return Decimal("0")


def _ordered_sections(
    sections_by_title: dict[str, list[TeamBreakdownLine]],
) -> list[tuple[str, list[TeamBreakdownLine]]]:
    stage_labels = {
        Match.Stage.GROUP: "Group stage",
        Match.Stage.ROUND_OF_32: "Round of 32",
        Match.Stage.ROUND_OF_16: "Round of 16",
        Match.Stage.QUARTERFINAL: "Quarterfinal",
        Match.Stage.SEMIFINAL: "Semifinal",
        Match.Stage.THIRD_PLACE: "Third-place Match",
        Match.Stage.FINAL: "Final",
    }
    title_order = {title: order for stage, order in STAGE_ORDER.items() for title in [stage_labels[stage]]}
    title_order["Tournament bonus"] = 99

    return sorted(
        sections_by_title.items(),
        key=lambda item: (title_order.get(item[0], 98), item[0]),
    )


def _opponent_for_team(match: Match, team: NationalTeam) -> NationalTeam | None:
    if match.home_team_id == team.id:
        return match.away_team
    return match.home_team


def _match_line_label(match: Match) -> str:
    if match.match_number is not None:
        return f"Match {match.match_number}"
    return match.get_stage_display()


def _match_line_description(opponent: NationalTeam | None, score_label: str) -> str:
    opponent_label = f"vs {opponent.name}" if opponent is not None else "vs TBD"
    if score_label:
        return f"{opponent_label} · {score_label}"
    return opponent_label


def _match_score_label(match: Match, team: NationalTeam, live_state=None) -> str:
    team_score, opponent_score = _score_for_team(match, team)
    score_label = f"{team_score}-{opponent_score}"

    if not match.went_to_penalties or live_state is None:
        return score_label

    if match.home_team_id == team.id:
        team_penalties = getattr(live_state, "penalty_home_score", None)
        opponent_penalties = getattr(live_state, "penalty_away_score", None)
    else:
        team_penalties = getattr(live_state, "penalty_away_score", None)
        opponent_penalties = getattr(live_state, "penalty_home_score", None)

    if team_penalties is None or opponent_penalties is None:
        return score_label

    return f"{score_label}, pens {team_penalties}-{opponent_penalties}"


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