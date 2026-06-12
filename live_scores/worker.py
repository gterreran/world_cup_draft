from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable, Iterable, Sequence

from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

from tournaments.models import Match, Tournament

from .broadcasts import broadcast_match_score_update
from .models import LiveMatchState, ProviderFixtureMapping
from .providers import (
    LiveScoreProviderConfigurationError,
    LiveScoreProviderError,
    NormalizedFixture,
    extract_fixture_list,
    get_provider_client,
    normalize_provider,
    provider_label,
)
from .services import (
    final_match_result_from_fixture,
    mapped_match_for_fixture,
    update_live_match_state,
)


LogFn = Callable[[str], None]

LIVE_LIKE_STATUSES = {
    LiveMatchState.Status.LIVE,
    LiveMatchState.Status.HALFTIME,
    LiveMatchState.Status.EXTRA_TIME,
    LiveMatchState.Status.PENALTIES,
}
FINAL_LIKE_STATUSES = {
    LiveMatchState.Status.FINAL,
    LiveMatchState.Status.POSTPONED,
    LiveMatchState.Status.CANCELLED,
}
MATCH_TERMINAL_STATUSES = [
    Match.Status.FINAL,
    Match.Status.POSTPONED,
    Match.Status.CANCELLED,
]


@dataclass(frozen=True)
class LiveScorePollResult:
    """Summary of one provider polling pass."""

    provider: str
    mode: str = "live"
    total_provider_fixtures: int = 0
    mapped_fixtures: int = 0
    unmapped_fixtures: int = 0
    skipped_tournament_fixtures: int = 0
    created_states: int = 0
    updated_states: int = 0
    unchanged_states: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    live_provider_fixture_ids: list[str] = field(default_factory=list)
    final_provider_fixture_ids: list[str] = field(default_factory=list)
    final_results_applied: int = 0
    final_results_skipped: int = 0
    projection_jobs_queued: int = 0
    unmapped_provider_fixture_ids: list[str] = field(default_factory=list)

    @property
    def touched_states(self) -> int:
        return self.created_states + self.updated_states + self.unchanged_states

    @property
    def has_live_games(self) -> bool:
        return bool(self.live_provider_fixture_ids)

    def summary(self) -> str:
        status_summary = ", ".join(
            f"{status}={count}" for status, count in sorted(self.status_counts.items())
        ) or "none"
        return (
            f"{provider_label(self.provider)} {self.mode} poll: "
            f"provider_fixtures={self.total_provider_fixtures}, "
            f"mapped={self.mapped_fixtures}, "
            f"created={self.created_states}, "
            f"updated={self.updated_states}, "
            f"unchanged={self.unchanged_states}, "
            f"live={len(self.live_provider_fixture_ids)}, "
            f"final_like={len(self.final_provider_fixture_ids)}, "
            f"final_applied={self.final_results_applied}, "
            f"final_skipped={self.final_results_skipped}, "
            f"projection_jobs_queued={self.projection_jobs_queued}, "
            f"unmapped={self.unmapped_fixtures}, "
            f"skipped_tournament={self.skipped_tournament_fixtures}, "
            f"statuses=[{status_summary}]"
        )


@dataclass(frozen=True)
class PollDecisionStatus:
    """Return whether the worker should use fast live polling right now."""

    should_poll_live: bool
    next_match: Match | None
    reason: str


# Backwards-compatible alias for older imports/docs from the previous slice.
PollWindowStatus = PollDecisionStatus


def poll_live_scores_once(
    *,
    provider: str | None = None,
    tournament: Tournament | None = None,
    league_id: str | None = None,
    season: str | None = None,
    status_codes: str | None = None,
    provider_timezone: str | None = None,
    apply_final_results: bool = False,
    log: LogFn | None = None,
) -> LiveScorePollResult:
    """Fetch current live fixtures and update mapped ``LiveMatchState`` rows."""

    normalized_provider = normalize_provider(provider)
    client = get_provider_client(normalized_provider)
    payload = client.live_fixtures(
        league_id=league_id,
        season=season,
        status_codes=status_codes,
        timezone=provider_timezone,
    )
    fixtures = _normalize_payload_fixtures(client, payload)
    return _process_normalized_fixtures(
        fixtures,
        provider=normalized_provider,
        mode="live",
        tournament=tournament,
        apply_final_results=apply_final_results,
        log=log,
    )


def poll_fixture_details_once(
    *,
    fixture_ids: Sequence[str],
    provider: str | None = None,
    tournament: Tournament | None = None,
    provider_timezone: str | None = None,
    batch_size: int = 20,
    apply_final_results: bool = False,
    log: LogFn | None = None,
) -> LiveScorePollResult:
    """Fetch normal fixture details by provider fixture id and update live state.

    This is the safety path used when a match may have disappeared from the
    live-only endpoint. It can also apply final local Match results when the
    caller enables ``apply_final_results``.
    """

    normalized_provider = normalize_provider(provider)
    cleaned_ids = _dedupe_preserving_order(str(value) for value in fixture_ids if value)
    if not cleaned_ids:
        return LiveScorePollResult(provider=normalized_provider, mode="details")

    client = get_provider_client(normalized_provider)
    fixtures: list[NormalizedFixture] = []
    for chunk in _chunked(cleaned_ids, batch_size):
        if not hasattr(client, "fixtures_by_ids"):
            raise LiveScoreProviderConfigurationError(
                f"{provider_label(normalized_provider)} does not support fixture-id detail polling."
            )
        payload = client.fixtures_by_ids(  # type: ignore[attr-defined]
            chunk,
            timezone=provider_timezone,
        )
        fixtures.extend(_normalize_payload_fixtures(client, payload))

    return _process_normalized_fixtures(
        fixtures,
        provider=normalized_provider,
        mode="details",
        tournament=tournament,
        apply_final_results=apply_final_results,
        log=log,
    )


def polling_decision_status(
    *,
    tournament: Tournament,
    provider: str | None = None,
    has_live_games: bool = False,
    now=None,
    kickoff_buffer_minutes: int | None = None,
) -> PollDecisionStatus:
    """Return whether kickoff proximity or tracked live state warrants fast polling."""

    normalized_provider = normalize_provider(provider)
    now = now or timezone.now()
    kickoff_buffer = kickoff_buffer_minutes
    if kickoff_buffer is None:
        kickoff_buffer = getattr(settings, "LIVE_SCORES_KICKOFF_BUFFER_MINUTES", 15)

    next_mapping = next_upcoming_mapping(
        tournament=tournament,
        provider=normalized_provider,
        now=now,
    )
    next_match = next_mapping.match if next_mapping else None

    if has_live_games:
        reason = "Fast polling because at least one provider fixture is currently tracked as live."
        if next_match:
            reason += f" Next mapped match: {next_match} at {next_match.kickoff_time}."
        return PollDecisionStatus(
            should_poll_live=True,
            next_match=next_match,
            reason=reason,
        )

    if next_match and next_match.kickoff_time:
        poll_starts_at = next_match.kickoff_time - timedelta(minutes=kickoff_buffer)
        if now >= poll_starts_at:
            return PollDecisionStatus(
                should_poll_live=True,
                next_match=next_match,
                reason=(
                    f"Fast polling because next mapped match starts within "
                    f"{kickoff_buffer} min: {next_match} at {next_match.kickoff_time}."
                ),
            )
        return PollDecisionStatus(
            should_poll_live=False,
            next_match=next_match,
            reason=(
                f"No live games tracked. Next mapped match: {next_match} "
                f"at {next_match.kickoff_time}; fast polling starts at {poll_starts_at}."
            ),
        )

    return PollDecisionStatus(
        should_poll_live=False,
        next_match=None,
        reason="No upcoming mapped matches found for this tournament/provider.",
    )


def poll_window_status(
    *,
    tournament: Tournament,
    provider: str | None = None,
    now=None,
    kickoff_buffer_minutes: int | None = None,
    active_window_minutes: int | None = None,
    has_live_games: bool = False,
) -> PollDecisionStatus:
    """Compatibility wrapper around the new decision logic.

    ``active_window_minutes`` is accepted but intentionally ignored. The worker
    no longer uses a fixed upper time window after kickoff.
    """

    return polling_decision_status(
        tournament=tournament,
        provider=provider,
        has_live_games=has_live_games,
        now=now,
        kickoff_buffer_minutes=kickoff_buffer_minutes,
    )


def next_upcoming_mapping(
    *,
    tournament: Tournament,
    provider: str | None = None,
    now=None,
) -> ProviderFixtureMapping | None:
    """Return the next upcoming mapped, non-terminal local match."""

    normalized_provider = normalize_provider(provider)
    now = now or timezone.now()
    return (
        _mapped_matches_for_provider(normalized_provider)
        .filter(
            match__tournament=tournament,
            match__kickoff_time__gt=now,
        )
        .exclude(match__status__in=MATCH_TERMINAL_STATUSES)
        .order_by("match__kickoff_time", "match__match_number")
        .first()
    )


def due_fixture_ids_for_status_check(
    *,
    tournament: Tournament,
    provider: str | None = None,
    now=None,
) -> list[str]:
    """Return mapped provider fixture ids that should receive low-frequency checks.

    During idle periods, the worker asks for normal fixture details for mapped
    local matches whose kickoff time has already passed and whose local match is
    not terminal. This catches finals even if the fixture has disappeared from
    the live-only provider endpoint.
    """

    normalized_provider = normalize_provider(provider)
    now = now or timezone.now()
    mappings = (
        _mapped_matches_for_provider(normalized_provider)
        .filter(
            match__tournament=tournament,
            match__kickoff_time__lte=now,
        )
        .exclude(match__status__in=MATCH_TERMINAL_STATUSES)
        .order_by("match__kickoff_time", "match__match_number")
    )
    return [mapping.provider_fixture_id for mapping in mappings if mapping.provider_fixture_id]



def live_state_fixture_ids_for_status_check(
    *,
    tournament: Tournament,
    provider: str | None = None,
) -> list[str]:
    """Return provider fixture ids for DB rows still marked live-like.

    This protects worker restarts and one-shot smoke tests. If the provider's
    live-only endpoint has already dropped a fixture, we can still confirm its
    final status through direct fixture-detail polling using the fixture id stored
    in ``LiveMatchState``.
    """

    normalized_provider = normalize_provider(provider)
    states = (
        LiveMatchState.objects.select_related("match")
        .filter(
            provider=normalized_provider,
            match__tournament=tournament,
            status__in=LIVE_LIKE_STATUSES,
        )
        .exclude(match__status__in=MATCH_TERMINAL_STATUSES)
        .order_by("match__kickoff_time", "match__match_number")
    )
    return [state.provider_fixture_id for state in states if state.provider_fixture_id]

def is_live_like_status(status: str | None) -> bool:
    return status in LIVE_LIKE_STATUSES


def is_final_like_status(status: str | None) -> bool:
    return status in FINAL_LIKE_STATUSES


def _process_normalized_fixtures(
    fixtures: Sequence[NormalizedFixture],
    *,
    provider: str,
    mode: str,
    tournament: Tournament | None,
    apply_final_results: bool = False,
    log: LogFn | None = None,
) -> LiveScorePollResult:
    created = updated = unchanged = mapped = unmapped = skipped_tournament = 0
    final_applied = final_skipped = projection_jobs_queued = 0
    unmapped_ids: list[str] = []
    live_ids: list[str] = []
    final_ids: list[str] = []
    status_counts: dict[str, int] = {}

    for fixture in fixtures:
        status_counts[fixture.status] = status_counts.get(fixture.status, 0) + 1
        if is_live_like_status(fixture.status):
            live_ids.append(fixture.provider_fixture_id)
        if is_final_like_status(fixture.status):
            final_ids.append(fixture.provider_fixture_id)

        match = mapped_match_for_fixture(fixture)
        if match is None:
            unmapped += 1
            unmapped_ids.append(fixture.provider_fixture_id)
            if log:
                log(_unmapped_log_line(fixture))
            continue

        if tournament is not None and match.tournament_id != tournament.id:
            skipped_tournament += 1
            continue

        result = update_live_match_state(match=match, fixture=fixture)
        mapped += 1
        if result.created:
            created += 1
            if log:
                log(_state_log_line("CREATED", fixture, match))
            broadcast_match_score_update(match, result.live_state)
        elif result.changed:
            updated += 1
            if log:
                log(_state_log_line("UPDATED", fixture, match))
            broadcast_match_score_update(match, result.live_state)
        else:
            unchanged += 1

        if apply_final_results and fixture.status == LiveMatchState.Status.FINAL:
            applied, skipped, queued = _apply_provider_final_result(
                fixture=fixture,
                match=match,
                log=log,
            )
            final_applied += applied
            final_skipped += skipped
            projection_jobs_queued += queued

    return LiveScorePollResult(
        provider=provider,
        mode=mode,
        total_provider_fixtures=len(fixtures),
        mapped_fixtures=mapped,
        unmapped_fixtures=unmapped,
        skipped_tournament_fixtures=skipped_tournament,
        created_states=created,
        updated_states=updated,
        unchanged_states=unchanged,
        status_counts=status_counts,
        live_provider_fixture_ids=_dedupe_preserving_order(live_ids),
        final_provider_fixture_ids=_dedupe_preserving_order(final_ids),
        final_results_applied=final_applied,
        final_results_skipped=final_skipped,
        projection_jobs_queued=projection_jobs_queued,
        unmapped_provider_fixture_ids=unmapped_ids,
    )


def _apply_provider_final_result(
    *,
    fixture: NormalizedFixture,
    match: Match,
    log: LogFn | None,
) -> tuple[int, int, int]:
    if match.status == Match.Status.FINAL:
        return 0, 0, 0

    final_result = final_match_result_from_fixture(match=match, fixture=fixture)
    if final_result is None:
        if log:
            log(
                f"SKIP FINAL APPLY: provider_fixture={fixture.provider_fixture_id} -> "
                f"{match} | could not safely derive local final result/winner."
            )
        return 0, 1, 0

    try:
        from tournaments.services import apply_final_match_result

        applied = apply_final_match_result(
            match=match,
            home_score=final_result.home_score,
            away_score=final_result.away_score,
            winner=final_result.winner,
            went_to_extra_time=final_result.went_to_extra_time,
            went_to_penalties=final_result.went_to_penalties,
            reason=f"Provider final result from {provider_label(fixture.provider)}.",
        )
    except ValidationError as exc:
        if log:
            log(
                f"SKIP FINAL APPLY: provider_fixture={fixture.provider_fixture_id} -> "
                f"{match} | validation error: {exc}"
            )
        return 0, 1, 0

    broadcast_match_score_update(applied.match)

    if log:
        log(
            f"FINAL APPLIED: provider_fixture={fixture.provider_fixture_id} -> "
            f"{applied.match} | {applied.match.home_score}-{applied.match.away_score} | "
            f"winner={applied.match.winner or '-'} | "
            f"queued_projection_jobs={applied.refresh.queued_count}"
        )

    return 1, 0, applied.refresh.queued_count


def _normalize_payload_fixtures(client, payload: dict) -> list[NormalizedFixture]:
    raw_fixtures = extract_fixture_list(payload)
    return [client.normalize_fixture(raw) for raw in raw_fixtures]


def _mapped_matches_for_provider(provider: str):
    return ProviderFixtureMapping.objects.filter(provider=provider).select_related(
        "match",
        "match__home_team",
        "match__away_team",
    )


def _chunked(values: Sequence[str], size: int) -> Iterable[list[str]]:
    if size <= 0:
        size = 20
    for start in range(0, len(values), size):
        yield list(values[start : start + size])


def _dedupe_preserving_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        output.append(value)
    return output


def _fixture_label(fixture: NormalizedFixture) -> str:
    home = fixture.home_team.name if fixture.home_team else "TBD"
    away = fixture.away_team.name if fixture.away_team else "TBD"
    return f"{home} {fixture.score_label} {away}"


def _state_log_line(prefix: str, fixture: NormalizedFixture, match: Match) -> str:
    minute = f" {fixture.minute}'" if fixture.minute is not None else ""
    return (
        f"{prefix}: provider_fixture={fixture.provider_fixture_id} -> "
        f"{match} | {_fixture_label(fixture)} | {fixture.status}{minute}"
    )


def _unmapped_log_line(fixture: NormalizedFixture) -> str:
    return (
        f"UNMAPPED LIVE FIXTURE: provider_fixture={fixture.provider_fixture_id} | "
        f"{_fixture_label(fixture)} | {fixture.status} | {fixture.starting_at or '-'}"
    )


__all__ = [
    "FINAL_LIKE_STATUSES",
    "LIVE_LIKE_STATUSES",
    "LiveScorePollResult",
    "PollDecisionStatus",
    "PollWindowStatus",
    "due_fixture_ids_for_status_check",
    "is_final_like_status",
    "is_live_like_status",
    "live_state_fixture_ids_for_status_check",
    "next_upcoming_mapping",
    "poll_fixture_details_once",
    "poll_live_scores_once",
    "poll_window_status",
    "polling_decision_status",
    "LiveScoreProviderConfigurationError",
    "LiveScoreProviderError",
]
