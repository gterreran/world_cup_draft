from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone as datetime_timezone
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Sequence
import unicodedata

from django.db import IntegrityError
from django.utils import timezone

from live_scores.models import ProviderFixtureMapping
from live_scores.providers import (
    NormalizedFixture,
    extract_fixture_list,
    get_provider_client,
    normalize_provider,
    provider_label,
)
from tournaments.models import Match, Tournament


MATCH_TERMINAL_STATUSES = [
    Match.Status.FINAL,
    Match.Status.POSTPONED,
    Match.Status.CANCELLED,
]

# Provider/team names are not guaranteed to match FIFA/local names exactly.
# Keep this list conservative: only aliases that are common and unambiguous.
TEAM_NAME_ALIASES = {
    "bosnia herzegovina": "bosnia and herzegovina",
    "bosnia herzogovina": "bosnia and herzegovina",
    "cape verde islands": "cape verde",
    "cote divoire": "cote d ivoire",
    "cote d ivoire": "cote d ivoire",
    "côte d ivoire": "cote d ivoire",
    "czech republic": "czechia",
    "d r congo": "congo dr",
    "democratic republic of congo": "congo dr",
    "dr congo": "congo dr",
    "iran": "ir iran",
    "ivory coast": "cote d ivoire",
    "korea republic": "korea republic",
    "republic of korea": "korea republic",
    "south korea": "korea republic",
    "turkey": "turkiye",
    "türkiye": "turkiye",
    "u s a": "united states",
    "usa": "united states",
    "united states of america": "united states",
}


@dataclass(frozen=True)
class CandidateMatch:
    match: Match
    confidence: float
    reason: str


@dataclass(frozen=True)
class AutoMappingResult:
    """Summary of an automatic provider-fixture mapping pass."""

    provider: str
    start_date: str
    end_date: str
    provider_fixtures: int = 0
    local_candidates: int = 0
    created: int = 0
    skipped_already_mapped_provider_fixture: int = 0
    skipped_no_candidate: int = 0
    skipped_below_threshold: int = 0
    skipped_integrity_error: int = 0
    created_provider_fixture_ids: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.created > 0

    def summary(self) -> str:
        return (
            f"{provider_label(self.provider)} auto-mapping: "
            f"window={self.start_date}..{self.end_date}, "
            f"provider_fixtures={self.provider_fixtures}, "
            f"local_candidates={self.local_candidates}, "
            f"created={self.created}, "
            f"already_mapped_provider={self.skipped_already_mapped_provider_fixture}, "
            f"no_candidate={self.skipped_no_candidate}, "
            f"below_threshold={self.skipped_below_threshold}, "
            f"integrity_skipped={self.skipped_integrity_error}"
        )


def discover_missing_provider_mappings(
    *,
    tournament: Tournament,
    provider: str | None = None,
    league_id: str | None = None,
    season: str | None = None,
    provider_timezone: str | None = None,
    lookback_days: int = 2,
    lookahead_days: int = 21,
    kickoff_tolerance_minutes: int = 180,
    threshold: float = 75.0,
    now=None,
) -> AutoMappingResult:
    """Create safe mappings for provider fixtures that became available later.

    API-Football may expose knockout fixtures only after the participant teams
    are known. The initial tournament mapping can therefore cover the group
    stage but miss Round-of-32/Round-of-16/etc. fixtures. This helper performs a
    conservative mapping pass for local, non-terminal matches that already have
    concrete home/away teams but do not yet have a mapping for the provider.
    """

    normalized_provider = normalize_provider(provider)
    now = now or timezone.now()
    lookback_days = max(0, int(lookback_days))
    lookahead_days = max(1, int(lookahead_days))

    start_date = (now - timedelta(days=lookback_days)).date()
    end_date = (now + timedelta(days=lookahead_days)).date()
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date + timedelta(days=1), time.min)
    if timezone.is_naive(start_dt):
        start_dt = timezone.make_aware(start_dt, timezone=timezone.get_current_timezone())
    if timezone.is_naive(end_dt):
        end_dt = timezone.make_aware(end_dt, timezone=timezone.get_current_timezone())

    local_matches = list(
        Match.objects.filter(
            tournament=tournament,
            kickoff_time__gte=start_dt,
            kickoff_time__lt=end_dt,
            home_team__isnull=False,
            away_team__isnull=False,
        )
        .exclude(status__in=MATCH_TERMINAL_STATUSES)
        .exclude(provider_mappings__provider=normalized_provider)
        .select_related("home_team", "away_team")
        .order_by("kickoff_time", "match_number", "id")
    )

    client = get_provider_client(normalized_provider)
    payload = client.fixtures_between(
        start_date.isoformat(),
        end_date.isoformat(),
        league_id=league_id,
        season=season,
        timezone=provider_timezone,
    )
    provider_fixtures = [client.normalize_fixture(raw) for raw in extract_fixture_list(payload)]

    existing_provider_fixture_ids = set(
        ProviderFixtureMapping.objects.filter(
            provider=normalized_provider,
            provider_fixture_id__in=[fixture.provider_fixture_id for fixture in provider_fixtures],
        ).values_list("provider_fixture_id", flat=True)
    )

    created = 0
    skipped_already_mapped = 0
    skipped_no_candidate = 0
    skipped_below_threshold = 0
    skipped_integrity_error = 0
    created_fixture_ids: list[str] = []
    available_matches: list[Match] = list(local_matches)

    for fixture in provider_fixtures:
        if not fixture.provider_fixture_id:
            skipped_no_candidate += 1
            continue
        if fixture.provider_fixture_id in existing_provider_fixture_ids:
            skipped_already_mapped += 1
            continue
        if not _fixture_has_concrete_teams(fixture):
            skipped_no_candidate += 1
            continue

        candidate = best_candidate(
            fixture,
            available_matches,
            kickoff_tolerance_minutes=kickoff_tolerance_minutes,
        )
        if candidate is None:
            skipped_no_candidate += 1
            continue
        if candidate.confidence < threshold:
            skipped_below_threshold += 1
            continue

        try:
            ProviderFixtureMapping.objects.create(
                provider=normalized_provider,
                provider_fixture_id=fixture.provider_fixture_id,
                match=candidate.match,
                provider_league_id=fixture.league_id,
                provider_season_id=fixture.season_id,
                provider_home_name=fixture.home_team.name if fixture.home_team else "",
                provider_away_name=fixture.away_team.name if fixture.away_team else "",
                provider_starting_at=fixture.starting_at,
                confidence=Decimal(str(round(candidate.confidence, 2))),
                notes=f"Auto-mapped by worker: {candidate.reason}",
                raw_payload=fixture.raw,
            )
        except IntegrityError:
            skipped_integrity_error += 1
            continue

        created += 1
        created_fixture_ids.append(fixture.provider_fixture_id)
        existing_provider_fixture_ids.add(fixture.provider_fixture_id)
        available_matches = [match for match in available_matches if match.id != candidate.match.id]

    return AutoMappingResult(
        provider=normalized_provider,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        provider_fixtures=len(provider_fixtures),
        local_candidates=len(local_matches),
        created=created,
        skipped_already_mapped_provider_fixture=skipped_already_mapped,
        skipped_no_candidate=skipped_no_candidate,
        skipped_below_threshold=skipped_below_threshold,
        skipped_integrity_error=skipped_integrity_error,
        created_provider_fixture_ids=created_fixture_ids,
    )


def best_candidate(
    fixture: NormalizedFixture,
    local_matches: Sequence[Match],
    *,
    kickoff_tolerance_minutes: int,
) -> CandidateMatch | None:
    best: CandidateMatch | None = None

    for match in local_matches:
        if not fixture.starting_at or not match.kickoff_time:
            time_score = 0.0
            minutes_apart = None
        else:
            local_kickoff = match.kickoff_time
            if timezone.is_naive(local_kickoff):
                local_kickoff = timezone.make_aware(local_kickoff, timezone=datetime_timezone.utc)
            minutes_apart = abs((local_kickoff - fixture.starting_at).total_seconds()) / 60
            if minutes_apart > kickoff_tolerance_minutes:
                continue
            time_score = max(0.0, 50.0 * (1.0 - (minutes_apart / kickoff_tolerance_minutes)))

        team_score = _team_similarity_score(fixture, match)
        confidence = min(100.0, time_score + team_score)
        reason = _reason(minutes_apart, time_score, team_score)

        if best is None or confidence > best.confidence:
            best = CandidateMatch(match=match, confidence=confidence, reason=reason)

    return best


def _fixture_has_concrete_teams(fixture: NormalizedFixture) -> bool:
    names = [
        fixture.home_team.name if fixture.home_team else "",
        fixture.away_team.name if fixture.away_team else "",
    ]
    return all(_normalize_name(name) not in {"", "tbd"} for name in names)


def _team_similarity_score(fixture: NormalizedFixture, match: Match) -> float:
    provider_home = fixture.home_team.name if fixture.home_team else ""
    provider_away = fixture.away_team.name if fixture.away_team else ""

    if not provider_home and not provider_away:
        return 0.0

    direct = (
        _similarity(provider_home, match.home_label) +
        _similarity(provider_away, match.away_label)
    ) / 2
    reversed_score = (
        _similarity(provider_home, match.away_label) +
        _similarity(provider_away, match.home_label)
    ) / 2

    # Up to 50 points from team names. Reversed home/away can still be useful,
    # but we penalize it because fixture home/away should normally match.
    return max(direct * 50.0, reversed_score * 35.0)


def _similarity(left: str, right: str) -> float:
    left = _normalize_name(left)
    right = _normalize_name(right)
    if not left or not right or right == "tbd":
        return 0.0
    if left == right:
        return 1.0
    if left in right or right in left:
        return 0.9
    return SequenceMatcher(None, left, right).ratio()


def _normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    keep = []
    for char in text.lower():
        if char.isalnum() or char.isspace():
            keep.append(char)
        else:
            keep.append(" ")
    normalized = " ".join("".join(keep).split())
    return TEAM_NAME_ALIASES.get(normalized, normalized)


def _reason(minutes_apart: float | None, time_score: float, team_score: float) -> str:
    if minutes_apart is None:
        time_part = "no kickoff comparison"
    else:
        time_part = f"kickoff Δ={minutes_apart:.0f} min"
    return f"{time_part}; time_score={time_score:.1f}; team_score={team_score:.1f}"


__all__ = [
    "AutoMappingResult",
    "CandidateMatch",
    "best_candidate",
    "discover_missing_provider_mappings",
]
