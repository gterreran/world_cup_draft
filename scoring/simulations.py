from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
import math
import random
import statistics
from typing import Callable

from assignments.models import TeamAssignment
from leagues.models import League, LeagueMember
from scoring.defaults import default_scoring_config, default_tiebreaker_config
from tournaments.models import Match, NationalTeam
from tournaments.third_place import (
    FIFA_THIRD_PLACE_OPPONENT_SLOTS,
    load_fifa_third_place_table,
)


DIRECT_SLOT_PREFIXES = {"1", "2"}


@dataclass
class TeamRunStats:
    points: Decimal = Decimal("0")
    wins: int = 0
    draws: int = 0
    losses: int = 0
    teams_advanced: int = 0
    best_finish_rank: int | None = None
    goal_difference: int = 0
    goals_scored: int = 0


@dataclass
class GroupTableRow:
    team: NationalTeam
    table_points: int = 0
    goal_difference: int = 0
    goals_scored: int = 0
    random_tiebreaker: float = 0.0


@dataclass
class SimulatedTeamTournament:
    champion: NationalTeam | None = None
    runner_up: NationalTeam | None = None
    third_place: NationalTeam | None = None
    fourth_place: NationalTeam | None = None
    qualified_from_group: set[int] = field(default_factory=set)
    team_stats: dict[int, TeamRunStats] = field(default_factory=dict)


@dataclass(frozen=True)
class SimulationSettings:
    runs: int = 10000
    mode: str = "seeded"
    seed: int | None = 42
    draw_prob: float = 0.24
    rank_elo_step: float = 8.0
    regulation_prob: float = 0.75
    extra_time_prob: float = 0.15


@dataclass(frozen=True)
class ManagerSimulationProjection:
    member: LeagueMember
    average_score: Decimal
    average_rank: Decimal
    first_pick_probability: Decimal
    top3_probability: Decimal
    champion_owner_probability: Decimal


@dataclass(frozen=True)
class SimulationBalanceMetrics:
    champion_owner_win_rate: float
    finalist_owner_win_rate: float
    champion_owner_top3_rate: float
    champion_owner_avg_rank: float
    avg_winning_score: float
    avg_second_score: float
    avg_first_second_gap: float
    avg_winner_top_team_share: float


@dataclass(frozen=True)
class LeagueSimulationResult:
    projections: dict[int, ManagerSimulationProjection]
    metrics: SimulationBalanceMetrics
    champion_team_counts: Counter
    runs: int
    mode: str


ProgressLogger = Callable[[str], None]


class SimulationConfigurationError(ValueError):
    """Raised when simulation inputs or settings are invalid."""


def simulate_league_forecast(
    league: League,
    *,
    settings: SimulationSettings | None = None,
    progress_logger: ProgressLogger | None = None,
) -> LeagueSimulationResult:
    """Simulate remaining tournament outcomes and forecast league standings.

    Completed matches are treated as fixed facts. Only unplayed matches are
    randomized. This makes the output suitable for live standings forecasts as
    the tournament progresses.
    """
    settings = settings or SimulationSettings()
    _validate_settings(settings)

    tournament = league.tournament
    members = list(league.members.all().order_by("display_name", "id"))
    if not members:
        raise SimulationConfigurationError("This league has no managers to simulate.")

    assignments = list(
        TeamAssignment.objects.filter(league=league)
        .select_related("member", "national_team")
        .order_by("member__display_name", "national_team__name")
    )
    if not assignments:
        raise SimulationConfigurationError("This league has no team assignments to simulate.")

    owner_by_team_id = {
        assignment.national_team_id: assignment.member_id
        for assignment in assignments
    }
    teams_by_member_id: dict[int, list[int]] = defaultdict(list)
    for assignment in assignments:
        teams_by_member_id[assignment.member_id].append(assignment.national_team_id)

    teams = list(
        NationalTeam.objects.filter(tournament=tournament).order_by("group", "name", "id")
    )
    teams_by_id = {team.id: team for team in teams}

    group_matches = list(
        Match.objects.filter(tournament=tournament, stage=Match.Stage.GROUP)
        .select_related("home_team", "away_team", "winner")
        .order_by("match_number", "id")
    )
    knockout_matches = list(
        Match.objects.filter(tournament=tournament)
        .exclude(stage=Match.Stage.GROUP)
        .select_related("home_team", "away_team", "winner")
        .order_by("match_number", "id")
    )
    if not group_matches or not knockout_matches:
        raise SimulationConfigurationError(
            "Tournament schedule must include group and knockout matches."
        )

    third_place_table = load_fifa_third_place_table()
    third_place_slots_by_opponent = _third_place_slots_by_opponent(knockout_matches)

    config = default_scoring_config() | league.scoring_config
    tiebreakers = league.tiebreaker_config or default_tiebreaker_config()

    rng = random.Random(settings.seed)

    champion_owner_win_count = 0
    finalist_owner_win_count = 0
    champion_owner_top3_count = 0
    champion_owner_rank_values: list[float] = []
    winning_scores: list[float] = []
    second_scores: list[float] = []
    gaps: list[float] = []
    winner_top_team_shares: list[float] = []
    manager_win_shares = Counter()
    manager_top3_counts = Counter()
    manager_score_totals: dict[int, Decimal] = defaultdict(Decimal)
    manager_rank_totals = Counter()
    champion_owner_counts = Counter()
    champion_team_counts = Counter()

    progress_interval = max(1, settings.runs // 10)

    for run_index in range(settings.runs):
        simulated = _simulate_tournament(
            teams=teams,
            teams_by_id=teams_by_id,
            group_matches=group_matches,
            knockout_matches=knockout_matches,
            third_place_table=third_place_table,
            third_place_slots_by_opponent=third_place_slots_by_opponent,
            config=config,
            rng=rng,
            mode=settings.mode,
            draw_prob=settings.draw_prob,
            rank_elo_step=settings.rank_elo_step,
            regulation_prob=settings.regulation_prob,
            extra_time_prob=settings.extra_time_prob,
        )

        manager_rows = _score_managers(
            members=members,
            teams_by_member_id=teams_by_member_id,
            team_stats=simulated.team_stats,
            tiebreakers=tiebreakers,
        )

        for position, row in enumerate(manager_rows, start=1):
            manager_score_totals[row["member_id"]] += row["points"]
            manager_rank_totals[row["member_id"]] += position

        top_score = manager_rows[0]["points"]
        winners = [row for row in manager_rows if row["points"] == top_score]
        winner_share = Decimal("1") / Decimal(len(winners))

        for row in winners:
            manager_win_shares[row["member_id"]] += float(winner_share)

        top3_member_ids = {row["member_id"] for row in manager_rows[:3]}
        for member_id in top3_member_ids:
            manager_top3_counts[member_id] += 1

        champion_owner_id = owner_by_team_id.get(simulated.champion.id) if simulated.champion else None
        runner_up_owner_id = owner_by_team_id.get(simulated.runner_up.id) if simulated.runner_up else None

        if simulated.champion:
            champion_team_counts[simulated.champion.name] += 1

        if champion_owner_id is not None:
            champion_owner_counts[champion_owner_id] += 1
            champion_owner_row_index = next(
                index for index, row in enumerate(manager_rows, start=1)
                if row["member_id"] == champion_owner_id
            )
            champion_owner_rank_values.append(float(champion_owner_row_index))

            if any(row["member_id"] == champion_owner_id for row in winners):
                champion_owner_win_count += 1

            if champion_owner_id in top3_member_ids:
                champion_owner_top3_count += 1

        finalist_owner_ids = {
            member_id
            for member_id in (champion_owner_id, runner_up_owner_id)
            if member_id is not None
        }
        if any(row["member_id"] in finalist_owner_ids for row in winners):
            finalist_owner_win_count += 1

        winning_scores.append(float(manager_rows[0]["points"]))
        second_score = _second_distinct_score(manager_rows)
        second_scores.append(float(second_score))
        gaps.append(float(manager_rows[0]["points"] - second_score))

        for row in winners:
            team_points = [
                simulated.team_stats.get(team_id, TeamRunStats()).points
                for team_id in teams_by_member_id.get(row["member_id"], [])
            ]
            if row["points"] > 0 and team_points:
                winner_top_team_shares.append(float(max(team_points) / row["points"]))

        if progress_logger and (run_index + 1) % progress_interval == 0:
            progress_logger(f"  completed {run_index + 1:,}/{settings.runs:,} simulation runs")

    metrics = SimulationBalanceMetrics(
        champion_owner_win_rate=champion_owner_win_count / settings.runs,
        finalist_owner_win_rate=finalist_owner_win_count / settings.runs,
        champion_owner_top3_rate=champion_owner_top3_count / settings.runs,
        champion_owner_avg_rank=(
            statistics.mean(champion_owner_rank_values)
            if champion_owner_rank_values
            else float("nan")
        ),
        avg_winning_score=statistics.mean(winning_scores),
        avg_second_score=statistics.mean(second_scores),
        avg_first_second_gap=statistics.mean(gaps),
        avg_winner_top_team_share=(
            statistics.mean(winner_top_team_shares)
            if winner_top_team_shares
            else float("nan")
        ),
    )

    projections = {}
    for member in members:
        projections[member.id] = ManagerSimulationProjection(
            member=member,
            average_score=_decimal_average(manager_score_totals[member.id], settings.runs),
            average_rank=_decimal_average(Decimal(manager_rank_totals[member.id]), settings.runs),
            first_pick_probability=_decimal_probability(
                manager_win_shares[member.id], settings.runs
            ),
            top3_probability=_decimal_probability(
                manager_top3_counts[member.id], settings.runs
            ),
            champion_owner_probability=_decimal_probability(
                champion_owner_counts[member.id], settings.runs
            ),
        )

    return LeagueSimulationResult(
        projections=projections,
        metrics=metrics,
        champion_team_counts=champion_team_counts,
        runs=settings.runs,
        mode=settings.mode,
    )


def _validate_settings(settings: SimulationSettings) -> None:
    if settings.runs <= 0:
        raise SimulationConfigurationError("runs must be positive.")
    if settings.mode not in {"seeded", "uniform"}:
        raise SimulationConfigurationError("mode must be either 'seeded' or 'uniform'.")
    if not 0 <= settings.draw_prob < 1:
        raise SimulationConfigurationError("draw_prob must be >= 0 and < 1.")
    if (
        settings.regulation_prob < 0
        or settings.extra_time_prob < 0
        or settings.regulation_prob + settings.extra_time_prob > 1
    ):
        raise SimulationConfigurationError(
            "regulation_prob and extra_time_prob must be non-negative and sum to <= 1."
        )


def _simulate_tournament(
    *,
    teams: list[NationalTeam],
    teams_by_id: dict[int, NationalTeam],
    group_matches: list[Match],
    knockout_matches: list[Match],
    third_place_table: dict[str, dict[str, str]],
    third_place_slots_by_opponent: dict[str, str],
    config: dict,
    rng: random.Random,
    mode: str,
    draw_prob: float,
    rank_elo_step: float,
    regulation_prob: float,
    extra_time_prob: float,
) -> SimulatedTeamTournament:
    team_stats = {team.id: TeamRunStats() for team in teams}
    group_rows = {
        team.id: GroupTableRow(team=team, random_tiebreaker=rng.random())
        for team in teams
    }

    for match in group_matches:
        if not match.home_team_id or not match.away_team_id:
            continue

        if match.is_complete:
            home_score, away_score = match.home_score, match.away_score
        else:
            outcome = _choose_group_outcome(
                home=match.home_team,
                away=match.away_team,
                rng=rng,
                mode=mode,
                draw_prob=draw_prob,
                rank_elo_step=rank_elo_step,
            )
            home_score, away_score = _sample_group_score(outcome, rng)

        _apply_group_match(
            home=match.home_team,
            away=match.away_team,
            home_score=home_score,
            away_score=away_score,
            config=config,
            group_rows=group_rows,
            team_stats=team_stats,
        )

    direct_slots, qualified_third_teams = _compute_group_qualification(
        teams=teams,
        group_rows=group_rows,
    )
    third_slots = _allocate_third_place_slots_for_simulation(
        qualified_third_teams=qualified_third_teams,
        third_place_table=third_place_table,
        third_place_slots_by_opponent=third_place_slots_by_opponent,
    )

    qualified_ids = {team.id for team in direct_slots.values()} | {team.id for team in third_slots.values()}
    for team_id in qualified_ids:
        team_stats[team_id].points += Decimal(str(config["qualify_knockout"]))
        team_stats[team_id].teams_advanced = 1

    winners: dict[int, NationalTeam] = {}
    losers: dict[int, NationalTeam] = {}

    simulated = SimulatedTeamTournament(
        qualified_from_group=qualified_ids,
        team_stats=team_stats,
    )

    for match in knockout_matches:
        home = _resolve_simulated_slot(
            match.home_slot,
            match.home_team,
            direct_slots,
            third_slots,
            winners,
            losers,
        )
        away = _resolve_simulated_slot(
            match.away_slot,
            match.away_team,
            direct_slots,
            third_slots,
            winners,
            losers,
        )

        if home is None or away is None:
            continue

        if match.is_complete and match.winner_id:
            winner = teams_by_id.get(match.winner_id)
            if winner is None:
                continue
            if home.id == winner.id:
                loser = away
            elif away.id == winner.id:
                loser = home
            else:
                # Completed database state should make this impossible. Skip
                # rather than inventing a result for a contradictory match.
                continue
            decision = _actual_knockout_decision(match)
        else:
            winner, loser = _choose_knockout_winner(
                home=home,
                away=away,
                rng=rng,
                mode=mode,
                rank_elo_step=rank_elo_step,
            )
            decision = _choose_knockout_decision(
                rng=rng,
                regulation_prob=regulation_prob,
                extra_time_prob=extra_time_prob,
            )

        _apply_knockout_match(
            match=match,
            winner=winner,
            loser=loser,
            decision=decision,
            config=config,
            team_stats=team_stats,
            simulated=simulated,
        )

        if match.match_number is not None:
            winners[match.match_number] = winner
            losers[match.match_number] = loser

    return simulated


def _choose_group_outcome(
    *,
    home: NationalTeam,
    away: NationalTeam,
    rng: random.Random,
    mode: str,
    draw_prob: float,
    rank_elo_step: float,
) -> str:
    if mode == "uniform":
        home_win_prob = (1 - draw_prob) / 2
    else:
        home_win_prob = (1 - draw_prob) * _rank_win_probability(home, away, rank_elo_step)

    roll = rng.random()
    if roll < home_win_prob:
        return "home"
    if roll < home_win_prob + draw_prob:
        return "draw"
    return "away"


def _choose_knockout_winner(
    *,
    home: NationalTeam,
    away: NationalTeam,
    rng: random.Random,
    mode: str,
    rank_elo_step: float,
) -> tuple[NationalTeam, NationalTeam]:
    if mode == "uniform":
        home_win_prob = 0.5
    else:
        home_win_prob = _rank_win_probability(home, away, rank_elo_step)

    if rng.random() < home_win_prob:
        return home, away
    return away, home


def _rank_win_probability(team: NationalTeam, opponent: NationalTeam, rank_elo_step: float) -> float:
    team_rank = team.fifa_rank or 100
    opponent_rank = opponent.fifa_rank or 100
    rating_diff = (opponent_rank - team_rank) * rank_elo_step
    return 1 / (1 + math.pow(10, -rating_diff / 400))


def _sample_group_score(outcome: str, rng: random.Random) -> tuple[int, int]:
    if outcome == "draw":
        goals = rng.choices([0, 1, 2, 3], weights=[2, 5, 3, 1], k=1)[0]
        return goals, goals

    winner_goals = rng.choices([1, 2, 3, 4, 5], weights=[4, 5, 3, 1, 0.3], k=1)[0]
    loser_goals = rng.randint(0, max(0, winner_goals - 1))

    if outcome == "home":
        return winner_goals, loser_goals
    return loser_goals, winner_goals


def _apply_group_match(
    *,
    home: NationalTeam,
    away: NationalTeam,
    home_score: int,
    away_score: int,
    config: dict,
    group_rows: dict[int, GroupTableRow],
    team_stats: dict[int, TeamRunStats],
) -> None:
    group_rows[home.id].goals_scored += home_score
    group_rows[away.id].goals_scored += away_score
    group_rows[home.id].goal_difference += home_score - away_score
    group_rows[away.id].goal_difference += away_score - home_score

    team_stats[home.id].goals_scored += home_score
    team_stats[away.id].goals_scored += away_score
    team_stats[home.id].goal_difference += home_score - away_score
    team_stats[away.id].goal_difference += away_score - home_score

    if home_score > away_score:
        group_rows[home.id].table_points += 3
        team_stats[home.id].points += Decimal(str(config["group_win"]))
        team_stats[away.id].points += Decimal(str(config["group_loss"]))
        team_stats[home.id].wins += 1
        team_stats[away.id].losses += 1
    elif away_score > home_score:
        group_rows[away.id].table_points += 3
        team_stats[away.id].points += Decimal(str(config["group_win"]))
        team_stats[home.id].points += Decimal(str(config["group_loss"]))
        team_stats[away.id].wins += 1
        team_stats[home.id].losses += 1
    else:
        group_rows[home.id].table_points += 1
        group_rows[away.id].table_points += 1
        team_stats[home.id].points += Decimal(str(config["group_draw"]))
        team_stats[away.id].points += Decimal(str(config["group_draw"]))
        team_stats[home.id].draws += 1
        team_stats[away.id].draws += 1


def _compute_group_qualification(
    *,
    teams: list[NationalTeam],
    group_rows: dict[int, GroupTableRow],
) -> tuple[dict[str, NationalTeam], list[NationalTeam]]:
    teams_by_group: dict[str, list[NationalTeam]] = defaultdict(list)
    for team in teams:
        if team.group:
            teams_by_group[team.group].append(team)

    direct_slots: dict[str, NationalTeam] = {}
    third_rows: list[GroupTableRow] = []

    for group, group_teams in teams_by_group.items():
        ranked_rows = sorted(
            (group_rows[team.id] for team in group_teams),
            key=_group_table_sort_key,
        )
        if len(ranked_rows) >= 1:
            direct_slots[f"1{group}"] = ranked_rows[0].team
        if len(ranked_rows) >= 2:
            direct_slots[f"2{group}"] = ranked_rows[1].team
        if len(ranked_rows) >= 3:
            third_rows.append(ranked_rows[2])

    best_third_rows = sorted(third_rows, key=_group_table_sort_key)[:8]
    return direct_slots, [row.team for row in best_third_rows]


def _group_table_sort_key(row: GroupTableRow) -> tuple:
    return (
        -row.table_points,
        -row.goal_difference,
        -row.goals_scored,
        row.team.fifa_rank or 999,
        row.random_tiebreaker,
    )


def _allocate_third_place_slots_for_simulation(
    *,
    qualified_third_teams: list[NationalTeam],
    third_place_table: dict[str, dict[str, str]],
    third_place_slots_by_opponent: dict[str, str],
) -> dict[str, NationalTeam]:
    if len(qualified_third_teams) != 8:
        return {}

    group_to_team = {team.group: team for team in qualified_third_teams}
    key = "".join(sorted(group_to_team))
    row = third_place_table.get(key)
    if not row:
        return {}

    allocation = {}
    for opponent_slot in FIFA_THIRD_PLACE_OPPONENT_SLOTS:
        schedule_slot = third_place_slots_by_opponent.get(opponent_slot)
        fifa_slot = row.get(opponent_slot)
        if not schedule_slot or not fifa_slot:
            continue
        team = group_to_team.get(fifa_slot[1:])
        if team is not None:
            allocation[schedule_slot] = team
    return allocation


def _third_place_slots_by_opponent(knockout_matches: list[Match]) -> dict[str, str]:
    slots_by_opponent = {}

    for match in knockout_matches:
        home_slot = (match.home_slot or "").strip()
        away_slot = (match.away_slot or "").strip()

        if _is_direct_winner_slot(home_slot) and _is_third_placeholder(away_slot):
            slots_by_opponent[home_slot] = away_slot
        if _is_direct_winner_slot(away_slot) and _is_third_placeholder(home_slot):
            slots_by_opponent[away_slot] = home_slot

    return slots_by_opponent


def _is_direct_winner_slot(slot: str) -> bool:
    return len(slot) >= 2 and slot[0] == "1" and slot[1:].isalpha()


def _is_third_placeholder(slot: str) -> bool:
    return len(slot) >= 2 and slot[0] == "3" and slot[1:].isalpha()


def _resolve_simulated_slot(
    slot: str,
    concrete_team: NationalTeam | None,
    direct_slots: dict[str, NationalTeam],
    third_slots: dict[str, NationalTeam],
    winners: dict[int, NationalTeam],
    losers: dict[int, NationalTeam],
) -> NationalTeam | None:
    slot = (slot or "").strip()

    if concrete_team is not None and not slot:
        return concrete_team

    if len(slot) >= 2 and slot[0] in DIRECT_SLOT_PREFIXES and slot[1:].isalpha():
        return direct_slots.get(slot)

    if _is_third_placeholder(slot):
        return third_slots.get(slot)

    if slot.startswith("W") and slot[1:].isdigit():
        return winners.get(int(slot[1:]))

    if slot.startswith("L") and slot[1:].isdigit():
        return losers.get(int(slot[1:]))

    return concrete_team


def _choose_knockout_decision(
    *,
    rng: random.Random,
    regulation_prob: float,
    extra_time_prob: float,
) -> str:
    roll = rng.random()
    if roll < regulation_prob:
        return "regulation"
    if roll < regulation_prob + extra_time_prob:
        return "extra_time"
    return "penalties"


def _actual_knockout_decision(match: Match) -> str:
    if match.went_to_penalties:
        return "penalties"
    if match.went_to_extra_time:
        return "extra_time"
    return "regulation"


def _apply_knockout_match(
    *,
    match: Match,
    winner: NationalTeam,
    loser: NationalTeam,
    decision: str,
    config: dict,
    team_stats: dict[int, TeamRunStats],
    simulated: SimulatedTeamTournament,
) -> None:
    winner_stats = team_stats[winner.id]
    loser_stats = team_stats[loser.id]

    winner_stats.wins += 1
    loser_stats.losses += 1

    if decision == "penalties":
        winner_stats.points += Decimal(str(config["knockout_win_penalties"]))
        loser_stats.points += Decimal(str(config["knockout_loss_penalties"]))
    elif decision == "extra_time":
        winner_stats.points += Decimal(str(config["knockout_win_extra_time"]))
        loser_stats.points += Decimal(str(config["knockout_loss_extra_time"]))
    else:
        winner_stats.points += Decimal(str(config["knockout_win_regulation"]))

    if match.stage == Match.Stage.FINAL:
        simulated.champion = winner
        simulated.runner_up = loser
        winner_stats.points += Decimal(str(config["champion_bonus"]))
        loser_stats.points += Decimal(str(config["runner_up_bonus"]))
        _set_finish_rank(winner_stats, 1)
        _set_finish_rank(loser_stats, 2)
    elif match.stage == Match.Stage.THIRD_PLACE:
        simulated.third_place = winner
        simulated.fourth_place = loser
        winner_stats.points += Decimal(str(config["third_place_bonus"]))
        loser_stats.points += Decimal(str(config["fourth_place_bonus"]))
        _set_finish_rank(winner_stats, 3)
        _set_finish_rank(loser_stats, 4)


def _set_finish_rank(stats: TeamRunStats, rank: int) -> None:
    if stats.best_finish_rank is None or rank < stats.best_finish_rank:
        stats.best_finish_rank = rank


def _score_managers(
    *,
    members: list[LeagueMember],
    teams_by_member_id: dict[int, list[int]],
    team_stats: dict[int, TeamRunStats],
    tiebreakers: list[str],
) -> list[dict]:
    rows = []
    for member in members:
        aggregate = TeamRunStats()
        for team_id in teams_by_member_id.get(member.id, []):
            stats = team_stats.get(team_id, TeamRunStats())
            aggregate.points += stats.points
            aggregate.wins += stats.wins
            aggregate.draws += stats.draws
            aggregate.losses += stats.losses
            aggregate.teams_advanced += stats.teams_advanced
            aggregate.goal_difference += stats.goal_difference
            aggregate.goals_scored += stats.goals_scored
            if stats.best_finish_rank is not None:
                _set_finish_rank(aggregate, stats.best_finish_rank)

        rows.append(
            {
                "member_id": member.id,
                "display_name": member.display_name,
                "points": aggregate.points,
                "wins": aggregate.wins,
                "draws": aggregate.draws,
                "losses": aggregate.losses,
                "teams_advanced": aggregate.teams_advanced,
                "goal_difference": aggregate.goal_difference,
                "goals_scored": aggregate.goals_scored,
                "best_finish_rank": aggregate.best_finish_rank,
            }
        )

    rows.sort(key=lambda row: _manager_sort_key(row, tiebreakers))
    return rows


def _manager_sort_key(row: dict, tiebreakers: list[str]) -> tuple:
    key = [-row["points"]]
    for tiebreaker in tiebreakers:
        if tiebreaker == "teams_advanced":
            key.append(-row["teams_advanced"])
        elif tiebreaker == "wins":
            key.append(-row["wins"])
        elif tiebreaker == "goal_difference":
            key.append(-row["goal_difference"])
        elif tiebreaker == "goals_scored":
            key.append(-row["goals_scored"])
        elif tiebreaker == "best_finish_rank":
            key.append(row["best_finish_rank"] or 999)
        else:
            key.append(0)
    key.append(row["display_name"].lower())
    return tuple(key)


def _second_distinct_score(manager_rows: list[dict]) -> Decimal:
    top_score = manager_rows[0]["points"]
    for row in manager_rows[1:]:
        if row["points"] != top_score:
            return row["points"]
    return top_score


def _decimal_average(total: Decimal, runs: int) -> Decimal:
    return (total / Decimal(runs)).quantize(Decimal("0.01"))


def _decimal_probability(total: float | int, runs: int) -> Decimal:
    return (Decimal(str(total)) / Decimal(runs)).quantize(Decimal("0.0001"))


def pct(value: float | Decimal) -> str:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return "n/a"
    if math.isnan(numeric):
        return "n/a"
    return f"{numeric * 100:.1f}%"
