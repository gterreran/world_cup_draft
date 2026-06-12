from __future__ import annotations

from django.conf import settings

from .api_football import ApiFootballClient
from .base import (
    DEFAULT_PROVIDER,
    PROVIDER_API_FOOTBALL,
    LiveScoreProviderConfigurationError,
    LiveScoreProviderError,
    NormalizedFixture,
    NormalizedTeam,
    extract_fixture_list,
)


PROVIDER_LABELS = {
    PROVIDER_API_FOOTBALL: "API-Football",
}


def normalize_provider(value: str | None = None) -> str:
    provider = (value or getattr(settings, "LIVE_SCORES_PROVIDER", DEFAULT_PROVIDER) or DEFAULT_PROVIDER).strip().lower()
    provider = provider.replace("-", "_")
    if provider in {"api_sports", "apisports", "api_football", "apifootball"}:
        return PROVIDER_API_FOOTBALL
    raise LiveScoreProviderConfigurationError(f"Unsupported live-score provider: {value!r}")


def provider_label(value: str | None = None) -> str:
    return PROVIDER_LABELS.get(normalize_provider(value), normalize_provider(value))


def get_provider_client(provider: str | None = None):
    normalized = normalize_provider(provider)
    if normalized == PROVIDER_API_FOOTBALL:
        return ApiFootballClient()
    raise LiveScoreProviderConfigurationError(f"Unsupported live-score provider: {provider!r}")


__all__ = [
    "ApiFootballClient",
    "DEFAULT_PROVIDER",
    "PROVIDER_API_FOOTBALL",
    "LiveScoreProviderConfigurationError",
    "LiveScoreProviderError",
    "NormalizedFixture",
    "NormalizedTeam",
    "extract_fixture_list",
    "get_provider_client",
    "normalize_provider",
    "provider_label",
]
