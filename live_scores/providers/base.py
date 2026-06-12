from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone as datetime_timezone
from typing import Any

from django.utils import timezone
from django.utils.dateparse import parse_datetime


PROVIDER_API_FOOTBALL = "api_football"
DEFAULT_PROVIDER = PROVIDER_API_FOOTBALL


class LiveScoreProviderError(RuntimeError):
    """Base exception for external live-score provider failures."""


class LiveScoreProviderConfigurationError(LiveScoreProviderError):
    """Raised when the active provider is missing required configuration."""


@dataclass(frozen=True)
class NormalizedTeam:
    provider_id: str
    name: str
    location: str


@dataclass(frozen=True)
class NormalizedFixture:
    """Provider-neutral fixture shape used by commands and workers.

    Provider clients should normalize their native payloads into this dataclass
    before app code tries to map/update local matches. The raw provider payload
    is still preserved for debugging while we learn each API's edge cases.
    """

    provider: str
    provider_fixture_id: str
    provider_match_number: int | None
    name: str
    league_id: str
    season_id: str
    starting_at: Any
    state_id: int | None
    state_code: str
    state_name: str
    status: str
    home_team: NormalizedTeam | None
    away_team: NormalizedTeam | None
    home_score: int | None
    away_score: int | None
    home_winner: bool | None
    away_winner: bool | None
    penalty_home_score: int | None
    penalty_away_score: int | None
    minute: int | None
    went_to_extra_time: bool
    went_to_penalties: bool
    raw: dict[str, Any]

    @property
    def score_label(self) -> str:
        if self.home_score is None or self.away_score is None:
            return "—"
        return f"{self.home_score}-{self.away_score}"


def extract_fixture_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Return a list from common API response envelopes."""

    data = payload.get("data")
    if data is None:
        data = payload.get("response", [])
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def parse_provider_datetime(value: Any):
    if not value:
        return None
    text = str(value).replace("T", " ")
    parsed = parse_datetime(text)
    if parsed is None:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone=datetime_timezone.utc)
    return parsed


def int_or_none(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
