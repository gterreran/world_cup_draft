from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from tournaments.models import Match

from .models import LiveMatchState, ProviderFixtureMapping
from .providers.base import NormalizedFixture


@dataclass(frozen=True)
class LiveStateUpdateResult:
    live_state: LiveMatchState
    created: bool
    changed: bool


@transaction.atomic
def update_live_match_state(
    *,
    match: Match,
    fixture: NormalizedFixture,
) -> LiveStateUpdateResult:
    """Create/update the transient live state for one mapped fixture.

    This does not update Match.home_score/away_score. Final result application
    will be handled by a later shared service so live polling does not trigger
    expensive scoring/projection recomputation every few seconds.
    """

    live_state, created = LiveMatchState.objects.select_for_update().get_or_create(
        match=match,
        defaults={
            "provider": fixture.provider,
            "provider_fixture_id": fixture.provider_fixture_id,
        },
    )

    changed = created
    updates = {
        "provider": fixture.provider,
        "provider_fixture_id": fixture.provider_fixture_id,
        "status": fixture.status,
        "provider_state_id": fixture.state_id,
        "provider_state_code": fixture.state_code,
        "provider_state_name": fixture.state_name,
        "minute": fixture.minute,
        "home_score": fixture.home_score,
        "away_score": fixture.away_score,
        "went_to_extra_time": fixture.went_to_extra_time,
        "went_to_penalties": fixture.went_to_penalties,
        "penalty_home_score": fixture.penalty_home_score,
        "penalty_away_score": fixture.penalty_away_score,
        "last_seen_at": timezone.now(),
        "raw_payload": fixture.raw,
    }

    for field, value in updates.items():
        if getattr(live_state, field) != value:
            setattr(live_state, field, value)
            changed = True

    if changed:
        live_state.save()

    return LiveStateUpdateResult(
        live_state=live_state,
        created=created,
        changed=changed,
    )


def mapped_match_for_fixture(fixture: NormalizedFixture) -> Match | None:
    """Return the local match mapped to a normalized provider fixture, if any."""

    if not fixture.provider_fixture_id:
        return None

    mapping = (
        ProviderFixtureMapping.objects.select_related(
            "match",
            "match__home_team",
            "match__away_team",
        )
        .filter(
            provider=fixture.provider,
            provider_fixture_id=fixture.provider_fixture_id,
        )
        .first()
    )
    if mapping is None:
        return None
    return mapping.match
