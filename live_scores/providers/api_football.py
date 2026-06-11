from __future__ import annotations

from typing import Any

import requests
from django.conf import settings

from .base import (
    PROVIDER_API_FOOTBALL,
    LiveScoreProviderConfigurationError,
    LiveScoreProviderError,
    NormalizedFixture,
    NormalizedTeam,
    int_or_none,
    parse_provider_datetime,
)


DEFAULT_BASE_URL = "https://v3.football.api-sports.io"
DEFAULT_WORLD_CUP_LEAGUE_ID = "1"
DEFAULT_WORLD_CUP_SEASON = "2026"
DEFAULT_LIVE_STATUS_CODES = "1H-HT-2H-ET-BT-P-LIVE"

FINAL_STATUS_CODES = {"FT", "AET", "PEN"}
LIVE_STATUS_CODES = {"1H", "2H", "LIVE"}
HALFTIME_STATUS_CODES = {"HT"}
EXTRA_TIME_STATUS_CODES = {"ET", "BT"}
PENALTY_STATUS_CODES = {"P"}
POSTPONED_STATUS_CODES = {"PST"}
CANCELLED_STATUS_CODES = {"CANC", "ABD", "AWD", "WO"}
DELAYED_STATUS_CODES = {"SUSP", "INT"}
SCHEDULED_STATUS_CODES = {"TBD", "NS"}


class ApiFootballClient:
    """Small API-Football/API-SPORTS client for live-score ingestion.

    The client keeps endpoint calls thin and provider-specific. The rest of the
    live_scores app works with NormalizedFixture objects so the provider can be
    swapped later without rewriting mapping/worker code.
    """

    provider = PROVIDER_API_FOOTBALL

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.api_key = api_key or getattr(settings, "API_FOOTBALL_API_KEY", "")
        if not self.api_key:
            raise LiveScoreProviderConfigurationError(
                "API_FOOTBALL_API_KEY is not configured. Add it to your environment first."
            )

        self.base_url = (base_url or getattr(settings, "API_FOOTBALL_BASE_URL", DEFAULT_BASE_URL)).rstrip("/")
        self.timeout = timeout or getattr(settings, "API_FOOTBALL_TIMEOUT_SECONDS", 15)
        self.session = session or requests.Session()

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not path.startswith("/"):
            path = f"/{path}"

        request_params = {key: value for key, value in (params or {}).items() if value not in (None, "")}
        url = f"{self.base_url}{path}"
        try:
            response = self.session.get(
                url,
                params=request_params,
                headers={"x-apisports-key": self.api_key},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LiveScoreProviderError(f"API-Football request failed: {exc}") from exc

        if response.status_code >= 400:
            body = response.text[:500]
            raise LiveScoreProviderError(
                f"API-Football returned HTTP {response.status_code} for {path}: {body}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise LiveScoreProviderError(f"API-Football returned invalid JSON for {path}.") from exc

        errors = payload.get("errors")
        if errors:
            raise LiveScoreProviderError(f"API-Football returned errors for {path}: {errors}")

        return payload

    def live_fixtures(
        self,
        *,
        league_id: str | None = None,
        season: str | None = None,
        status_codes: str | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        return self.get(
            "/fixtures",
            params=_world_cup_params(
                league_id=league_id,
                season=season,
                status=status_codes or getattr(settings, "API_FOOTBALL_LIVE_STATUS_CODES", DEFAULT_LIVE_STATUS_CODES),
                timezone=timezone,
            ),
        )

    def fixtures_by_date(
        self,
        date: str,
        *,
        league_id: str | None = None,
        season: str | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        return self.get(
            "/fixtures",
            params=_world_cup_params(
                league_id=league_id,
                season=season,
                date=date,
                timezone=timezone,
            ),
        )

    def fixtures_between(
        self,
        start_date: str,
        end_date: str,
        *,
        league_id: str | None = None,
        season: str | None = None,
        timezone: str | None = None,
    ) -> dict[str, Any]:
        return self.get(
            "/fixtures",
            params=_world_cup_params(
                league_id=league_id,
                season=season,
                from_date=start_date,
                to_date=end_date,
                timezone=timezone,
            ),
        )

    def normalize_fixture(self, raw: dict[str, Any]) -> NormalizedFixture:
        return normalize_fixture(raw)


def _world_cup_params(
    *,
    league_id: str | None = None,
    season: str | None = None,
    date: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    status: str | None = None,
    timezone: str | None = None,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "league": league_id or getattr(settings, "API_FOOTBALL_WORLD_CUP_LEAGUE_ID", DEFAULT_WORLD_CUP_LEAGUE_ID),
        "season": season or getattr(settings, "API_FOOTBALL_WORLD_CUP_SEASON", DEFAULT_WORLD_CUP_SEASON),
    }
    if date:
        params["date"] = date
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    if status:
        params["status"] = status
    if timezone:
        params["timezone"] = timezone
    return params


def normalize_fixture(raw: dict[str, Any]) -> NormalizedFixture:
    fixture = raw.get("fixture") if isinstance(raw.get("fixture"), dict) else {}
    league = raw.get("league") if isinstance(raw.get("league"), dict) else {}
    teams = raw.get("teams") if isinstance(raw.get("teams"), dict) else {}
    goals = raw.get("goals") if isinstance(raw.get("goals"), dict) else {}
    score = raw.get("score") if isinstance(raw.get("score"), dict) else {}
    status = fixture.get("status") if isinstance(fixture.get("status"), dict) else {}

    home_team = _extract_team(teams.get("home"), location="home")
    away_team = _extract_team(teams.get("away"), location="away")
    home_score, away_score = _extract_current_score(goals, score)
    penalty_home_score, penalty_away_score = _extract_score_part(score, "penalty")
    state_code = str(status.get("short") or "")
    state_name = str(status.get("long") or state_code or "")

    return NormalizedFixture(
        provider=PROVIDER_API_FOOTBALL,
        provider_fixture_id=str(fixture.get("id") or ""),
        name=_fixture_name(home_team, away_team),
        league_id=str(league.get("id") or ""),
        season_id=str(league.get("season") or ""),
        starting_at=parse_provider_datetime(fixture.get("date")),
        state_id=None,
        state_code=state_code,
        state_name=state_name,
        status=normalize_state(state_code=state_code),
        home_team=home_team,
        away_team=away_team,
        home_score=home_score,
        away_score=away_score,
        penalty_home_score=penalty_home_score,
        penalty_away_score=penalty_away_score,
        minute=int_or_none(status.get("elapsed")),
        went_to_extra_time=_has_score_part(score, "extratime") or state_code in {"ET", "BT", "AET", "P", "PEN"},
        went_to_penalties=_has_score_part(score, "penalty") or state_code in {"P", "PEN"},
        raw=raw,
    )


def normalize_state(*, state_code: str = "") -> str:
    """Map API-Football fixture status codes into coarse app statuses."""

    code = (state_code or "").upper()
    if code in FINAL_STATUS_CODES:
        return "final"
    if code in HALFTIME_STATUS_CODES:
        return "halftime"
    if code in PENALTY_STATUS_CODES:
        return "penalties"
    if code in EXTRA_TIME_STATUS_CODES:
        return "extra_time"
    if code in LIVE_STATUS_CODES:
        return "live"
    if code in POSTPONED_STATUS_CODES:
        return "postponed"
    if code in CANCELLED_STATUS_CODES:
        return "cancelled"
    if code in DELAYED_STATUS_CODES:
        return "suspended"
    if code in SCHEDULED_STATUS_CODES:
        return "scheduled"
    return "unknown"


def _extract_team(raw_team: Any, *, location: str) -> NormalizedTeam | None:
    if not isinstance(raw_team, dict):
        return None
    return NormalizedTeam(
        provider_id=str(raw_team.get("id") or ""),
        name=str(raw_team.get("name") or ""),
        location=location,
    )


def _extract_current_score(goals: dict[str, Any], score: dict[str, Any]) -> tuple[int | None, int | None]:
    goal_home = int_or_none(goals.get("home"))
    goal_away = int_or_none(goals.get("away"))
    if goal_home is not None or goal_away is not None:
        return goal_home, goal_away

    for part in ("fulltime", "extratime"):
        home, away = _extract_score_part(score, part)
        if home is not None or away is not None:
            return home, away
    return None, None


def _extract_score_part(score: dict[str, Any], part: str) -> tuple[int | None, int | None]:
    section = score.get(part)
    if not isinstance(section, dict):
        return None, None
    return int_or_none(section.get("home")), int_or_none(section.get("away"))


def _has_score_part(score: dict[str, Any], part: str) -> bool:
    home, away = _extract_score_part(score, part)
    return home is not None or away is not None


def _fixture_name(home_team: NormalizedTeam | None, away_team: NormalizedTeam | None) -> str:
    home = home_team.name if home_team else "TBD"
    away = away_team.name if away_team else "TBD"
    return f"{home} vs {away}"
