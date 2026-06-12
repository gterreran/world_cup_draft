from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction

from tournaments.models import Match

from tournaments.standings import compute_group_standings
from tournaments.qualification import compute_qualification
from tournaments.qualification_status import compute_group_qualification_status


@dataclass(frozen=True)
class FinalResultRefreshSummary:
    league_count: int
    queued_count: int
    unavailable_messages: list[str]
    refresh_results: list[dict[str, Any]]


@dataclass(frozen=True)
class FinalResultApplyResult:
    match: Match
    changed: bool
    refresh: FinalResultRefreshSummary


@transaction.atomic
def save_final_match_result(
    *,
    match: Match,
    home_score: int,
    away_score: int,
    winner=None,
    went_to_extra_time: bool = False,
    went_to_penalties: bool = False,
) -> bool:
    """Save one final result on ``Match`` and return whether relevant fields changed.

    This is intentionally limited to the local tournament model. It does not
    recompute bracket progression, standings, or projections; callers that need
    the full tournament refresh should use ``apply_final_match_result``.
    """

    # Lock only the local Match row. Do not combine select_for_update()
    # with select_related() here: several Match relations are nullable for
    # future/bracket-slot matches, and PostgreSQL rejects FOR UPDATE on the
    # nullable side of an outer join. Accessing related teams below is safe;
    # Django will fetch them normally inside the same transaction after the
    # Match row itself has been locked.
    match = Match.objects.select_for_update().get(pk=match.pk)

    resolved_winner = _resolve_winner(
        match=match,
        home_score=home_score,
        away_score=away_score,
        winner=winner,
        went_to_extra_time=went_to_extra_time,
        went_to_penalties=went_to_penalties,
    )

    if went_to_penalties:
        went_to_extra_time = True

    before = _match_result_snapshot(match)

    match.home_score = home_score
    match.away_score = away_score
    match.status = Match.Status.FINAL
    match.went_to_extra_time = bool(went_to_extra_time)
    match.went_to_penalties = bool(went_to_penalties)
    match.winner = resolved_winner

    match.save(
        update_fields=[
            "home_score",
            "away_score",
            "status",
            "went_to_extra_time",
            "went_to_penalties",
            "winner",
        ]
    )

    return before != _match_result_snapshot(match)


def apply_final_match_result(
    *,
    match: Match,
    home_score: int,
    away_score: int,
    winner=None,
    went_to_extra_time: bool = False,
    went_to_penalties: bool = False,
    reason: str = "Match result changed.",
) -> FinalResultApplyResult:
    """Apply a final result and refresh all derived tournament/league state.

    Manual result edits and provider-driven final-score ingestion should both
    use this service so they share exactly one path for:

    - saving the local final ``Match`` result;
    - recomputing tournament progression/team statuses;
    - recomputing standings for every league using the tournament;
    - marking projections stale and queuing projection recompute jobs.
    """

    changed = save_final_match_result(
        match=match,
        home_score=home_score,
        away_score=away_score,
        winner=winner,
        went_to_extra_time=went_to_extra_time,
        went_to_penalties=went_to_penalties,
    )

    # Re-read with related fields after the save so callers/loggers get the
    # current object state even if they passed an older instance.
    match = Match.objects.select_related(
        "tournament",
        "home_team",
        "away_team",
        "winner",
    ).get(pk=match.pk)

    from scoring.services import refresh_leagues_after_tournament_change
    from tournaments.progression import recompute_tournament_progression

    recompute_tournament_progression(match.tournament)
    refresh_results = refresh_leagues_after_tournament_change(
        match.tournament,
        reason=reason,
    )

    summary = FinalResultRefreshSummary(
        league_count=len(refresh_results),
        queued_count=sum(1 for result in refresh_results if result.get("queued")),
        unavailable_messages=[
            result.get("message", "")
            for result in refresh_results
            if result.get("status") == "unavailable"
        ],
        refresh_results=refresh_results,
    )

    return FinalResultApplyResult(
        match=match,
        changed=changed,
        refresh=summary,
    )


def _resolve_winner(
    *,
    match: Match,
    home_score: int,
    away_score: int,
    winner,
    went_to_extra_time: bool,
    went_to_penalties: bool,
):
    """Resolve the local winner for a completed match.

    Group-stage draws legitimately have no winner, but non-draw final scores
    should still populate ``Match.winner`` for consistency with display/bracket
    code and with manually entered results. Knockout ties require an explicit
    winner because the regulation/fulltime score alone is not enough to know
    who advanced.
    """

    # In this app, group-stage matches never store a winner. Group standings are
    # computed from the final score, and Match.clean() intentionally rejects a
    # winner on group-stage rows. Provider payloads may still include winner
    # flags for group games, so ignore them here before validating/saving.
    if match.stage == Match.Stage.GROUP:
        return None

    if winner is not None:
        winner_id = winner.id if hasattr(winner, "id") else winner
        if winner_id == match.home_team_id:
            return match.home_team
        if winner_id == match.away_team_id:
            return match.away_team
        raise ValidationError("Winner must be one of the two teams in the match.")

    if home_score > away_score:
        return match.home_team
    if away_score > home_score:
        return match.away_team

    if went_to_penalties:
        raise ValidationError("Penalty shootouts require an explicit winner.")

    raise ValidationError("Tied knockout matches require an explicit winner.")


def _match_result_snapshot(match: Match) -> tuple:
    return (
        match.status,
        match.home_score,
        match.away_score,
        match.winner_id,
        match.went_to_extra_time,
        match.went_to_penalties,
    )


def build_group_stage_context(tournament):
    standings_by_group = compute_group_standings(tournament)
    qualification = compute_qualification(tournament)

    qualified_team_ids = {
        team.id
        for team in qualification.slot_map.values()
    }

    best_third_team_ids = {
        standing.team.id
        for standing in qualification.best_third_place_teams
    }

    output = []


    qualification_status = compute_group_qualification_status(tournament)

    for group_name, standings in standings_by_group.items():
        matches = (
            Match.objects.filter(
                tournament=tournament,
                stage=Match.Stage.GROUP,
            ).filter(
                models.Q(group=group_name)
                | models.Q(home_team__group=group_name)
                | models.Q(away_team__group=group_name)
            )
            .select_related("home_team", "away_team")
            .order_by("kickoff_time", "match_number")
        )

        rows = []

        for row in standings:
            team_status = qualification_status.get(row.team.id, {})

            qualification_label = team_status.get("label", "")
            qualification_class = team_status.get("class", "")

            rows.append(
                {
                    "standing": row,
                    "qualification_label": qualification_label,
                    "qualification_class": qualification_class,
                }
            )

        output.append(
            {
                "name": group_name,
                "standings": rows,
                "matches": matches,
            }
        )

    return output
