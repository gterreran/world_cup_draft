from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from django.db import transaction
from django.utils import timezone

from tournaments.models import Match

from .models import LiveMatchState, ProviderFixtureMapping
from .providers.base import NormalizedFixture


TEAM_NAME_ALIASES = {
    "south korea": "korea republic",
    "korea south": "korea republic",
    "czech republic": "czechia",
    "usa": "united states",
    "united states of america": "united states",
    "ivory coast": "cote divoire",
    "côte d'ivoire": "cote divoire",
    "cote d ivoire": "cote divoire",
    "cape verde islands": "cape verde",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "iran": "ir iran",
    "bosnia & herzegovina": "bosnia and herzegovina",
    "bosnia herzegovina": "bosnia and herzegovina",
}


@dataclass(frozen=True)
class LiveStateUpdateResult:
    live_state: LiveMatchState
    created: bool
    changed: bool


@dataclass(frozen=True)
class ProviderFinalResult:
    home_score: int
    away_score: int
    winner: object | None
    went_to_extra_time: bool
    went_to_penalties: bool
    orientation: str


@transaction.atomic
def update_live_match_state(
    *,
    match: Match,
    fixture: NormalizedFixture,
) -> LiveStateUpdateResult:
    """Create/update the transient live state for one mapped fixture.

    This does not update Match.home_score/away_score. Final result application
    is handled by the shared tournament service so live polling does not trigger
    expensive scoring/projection recomputation every few seconds.

    ``changed`` deliberately tracks display-relevant changes only. The worker
    still refreshes ``last_seen_at`` and ``raw_payload`` on every seen fixture,
    but those bookkeeping writes should not be treated as score/status changes.
    """

    live_state, created = LiveMatchState.objects.select_for_update().get_or_create(
        match=match,
        defaults={
            "provider": fixture.provider,
            "provider_fixture_id": fixture.provider_fixture_id,
        },
    )

    changed = created
    display_updates = {
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
    }

    update_fields: set[str] = set()
    for field, value in display_updates.items():
        if getattr(live_state, field) != value:
            setattr(live_state, field, value)
            update_fields.add(field)
            changed = True

    live_state.last_seen_at = timezone.now()
    live_state.raw_payload = fixture.raw
    update_fields.update({"last_seen_at", "raw_payload", "updated_at"})

    live_state.save(update_fields=sorted(update_fields))

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


def final_match_result_from_fixture(
    *,
    match: Match,
    fixture: NormalizedFixture,
) -> ProviderFinalResult | None:
    """Return a local final-result payload from a provider fixture.

    The provider fixture might theoretically have the opposite home/away order
    from the local Match. We detect direct/reversed orientation from team names
    and swap scores/winner flags when needed. If orientation cannot be determined
    safely, return None rather than risking a wrong final result.
    """

    if fixture.home_score is None or fixture.away_score is None:
        return None

    orientation = fixture_orientation_for_match(match=match, fixture=fixture)
    if orientation is None:
        return None

    if orientation == "direct":
        home_score = fixture.home_score
        away_score = fixture.away_score
        provider_home_winner = fixture.home_winner
        provider_away_winner = fixture.away_winner
    else:
        home_score = fixture.away_score
        away_score = fixture.home_score
        provider_home_winner = fixture.away_winner
        provider_away_winner = fixture.home_winner

    winner = None
    if match.stage != Match.Stage.GROUP:
        if provider_home_winner is True:
            winner = match.home_team
        elif provider_away_winner is True:
            winner = match.away_team
        elif home_score > away_score:
            winner = match.home_team
        elif away_score > home_score:
            winner = match.away_team
        else:
            # Tied knockout final without provider winner flags is not safe to
            # commit automatically, especially for penalty shootouts.
            return None

    return ProviderFinalResult(
        home_score=home_score,
        away_score=away_score,
        winner=winner,
        went_to_extra_time=fixture.went_to_extra_time,
        went_to_penalties=fixture.went_to_penalties,
        orientation=orientation,
    )


def fixture_orientation_for_match(
    *,
    match: Match,
    fixture: NormalizedFixture,
) -> str | None:
    provider_home = fixture.home_team.name if fixture.home_team else ""
    provider_away = fixture.away_team.name if fixture.away_team else ""

    if not provider_home or not provider_away or not match.home_team_id or not match.away_team_id:
        return None

    direct = (
        _team_similarity(provider_home, match.home_team.name)
        + _team_similarity(provider_away, match.away_team.name)
    ) / 2
    reversed_score = (
        _team_similarity(provider_home, match.away_team.name)
        + _team_similarity(provider_away, match.home_team.name)
    ) / 2

    if direct >= 0.9 and direct >= reversed_score:
        return "direct"
    if reversed_score >= 0.9:
        return "reversed"
    return None


def _team_similarity(left: str, right: str) -> float:
    left = _normalize_team_name(left)
    right = _normalize_team_name(right)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.9
    return SequenceMatcher(None, left, right).ratio()


def _normalize_team_name(value: str) -> str:
    text = value.lower().strip()
    text = TEAM_NAME_ALIASES.get(text, text)
    keep = []
    for char in text:
        if char.isalnum() or char.isspace():
            keep.append(char)
        else:
            keep.append(" ")
    normalized = " ".join("".join(keep).split())
    return TEAM_NAME_ALIASES.get(normalized, normalized)
