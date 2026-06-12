from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone as datetime_timezone
from decimal import Decimal
from difflib import SequenceMatcher
import unicodedata

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Min
from django.utils import timezone

from live_scores.models import ProviderFixtureMapping
from live_scores.providers import (
    LiveScoreProviderConfigurationError,
    LiveScoreProviderError,
    NormalizedFixture,
    extract_fixture_list,
    get_provider_client,
    normalize_provider,
    provider_label,
)
from tournaments.models import Match, Tournament


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


class Command(BaseCommand):
    help = "Dry-run or create provider fixture mappings for local tournament matches."

    def add_arguments(self, parser):
        parser.add_argument("tournament_slug", help="Tournament slug, e.g. world-cup-2026.")
        parser.add_argument(
            "--provider",
            default=None,
            help="Provider to inspect. Defaults to LIVE_SCORES_PROVIDER.",
        )
        parser.add_argument(
            "--date",
            help="Single provider fixture date to fetch, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--start-date",
            help="Start provider fixture date, YYYY-MM-DD. Must be used with --end-date.",
        )
        parser.add_argument(
            "--end-date",
            help="End provider fixture date, YYYY-MM-DD. Must be used with --start-date.",
        )
        parser.add_argument(
            "--league-id",
            default=None,
            help="Provider league/competition id. Defaults to the configured World Cup id.",
        )
        parser.add_argument(
            "--season",
            default=None,
            help="Provider season. Defaults to the configured World Cup season.",
        )
        parser.add_argument(
            "--timezone",
            default=None,
            help="Optional provider timezone parameter, e.g. America/Chicago.",
        )
        parser.add_argument(
            "--kickoff-tolerance-minutes",
            type=int,
            default=180,
            help="Maximum kickoff-time difference for candidate matches. Defaults to 180.",
        )
        parser.add_argument(
            "--threshold",
            type=float,
            default=75.0,
            help="Minimum confidence required when --commit is used. Defaults to 75.",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually create/update mapping rows. Default is dry-run only.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit provider fixtures processed, useful while testing. 0 means no limit.",
        )

    def handle(self, *args, **options):
        tournament = _get_tournament(options["tournament_slug"])
        provider = normalize_provider(options.get("provider"))
        start_date, end_date = _resolve_date_range(tournament, options)

        try:
            client = get_provider_client(provider)
            payload = _fetch_provider_payload(client, options, start_date, end_date)
        except LiveScoreProviderConfigurationError as exc:
            raise CommandError(str(exc)) from exc
        except LiveScoreProviderError as exc:
            raise CommandError(str(exc)) from exc

        provider_fixtures = [client.normalize_fixture(raw) for raw in extract_fixture_list(payload)]
        if options["limit"]:
            provider_fixtures = provider_fixtures[: options["limit"]]

        local_matches = list(
            Match.objects.filter(tournament=tournament)
            .select_related("home_team", "away_team")
            .order_by("kickoff_time", "match_number", "id")
        )

        provider_name = provider_label(provider)
        if not provider_fixtures:
            self.stdout.write(self.style.WARNING(f"No {provider_name} fixtures returned."))
            return
        if not local_matches:
            self.stdout.write(self.style.WARNING(f"No local matches found for {tournament.slug}."))
            return

        self.stdout.write(
            f"Mapping {len(provider_fixtures)} {provider_name} fixture(s) against "
            f"{len(local_matches)} local match(es)."
        )
        if not options["commit"]:
            self.stdout.write(self.style.WARNING("Dry run only. Re-run with --commit to save mappings."))

        created = 0
        updated = 0
        skipped = 0
        match_number_checked = 0
        match_number_mismatches = 0
        unmapped_match_numbers = 0

        for fixture in provider_fixtures:
            candidate = best_candidate(
                fixture,
                local_matches,
                kickoff_tolerance_minutes=options["kickoff_tolerance_minutes"],
            )
            if candidate is None:
                skipped += 1
                self.stdout.write(self.style.WARNING(_format_unmapped(fixture, "no local candidate")))
                continue

            local = candidate.match
            provider_pair = _fixture_pair_label(fixture)
            local_pair = f"{local.home_label} vs {local.away_label}"
            match_number_note = _match_number_note(fixture, local)
            if fixture.provider_match_number is None:
                unmapped_match_numbers += 1
            else:
                match_number_checked += 1
                if _local_match_number(local) != fixture.provider_match_number:
                    match_number_mismatches += 1

            line = (
                f"{fixture.provider_fixture_id} | {provider_pair} | {fixture.starting_at or '—'} "
                f"→ Match {local.match_number or local.id}: {local_pair} | "
                f"confidence={candidate.confidence:.1f} | {candidate.reason}"
                f"{match_number_note}"
            )

            if candidate.confidence < options["threshold"]:
                skipped += 1
                self.stdout.write(self.style.WARNING(f"SKIP below threshold: {line}"))
                continue

            if not options["commit"]:
                if "MATCH NUMBER MISMATCH" in match_number_note:
                    self.stdout.write(self.style.WARNING(line))
                else:
                    self.stdout.write(line)
                continue

            mapping, was_created = ProviderFixtureMapping.objects.update_or_create(
                provider=provider,
                provider_fixture_id=fixture.provider_fixture_id,
                defaults={
                    "match": local,
                    "provider_league_id": fixture.league_id,
                    "provider_season_id": fixture.season_id,
                    "provider_home_name": fixture.home_team.name if fixture.home_team else "",
                    "provider_away_name": fixture.away_team.name if fixture.away_team else "",
                    "provider_starting_at": fixture.starting_at,
                    "confidence": Decimal(str(round(candidate.confidence, 2))),
                    "notes": _mapping_notes(candidate.reason, match_number_note),
                    "raw_payload": fixture.raw,
                },
            )
            if was_created:
                created += 1
                self.stdout.write(self.style.SUCCESS(f"CREATED: {line}"))
            else:
                updated += 1
                self.stdout.write(self.style.SUCCESS(f"UPDATED: {line}"))

        if match_number_checked:
            if match_number_mismatches:
                self.stdout.write(
                    self.style.WARNING(
                        f"Provider match-number check: {match_number_mismatches} mismatch(es) "
                        f"out of {match_number_checked} fixture(s) with explicit provider match numbers."
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Provider match-number check: all {match_number_checked} explicit provider match number(s) matched."
                    )
                )
        elif unmapped_match_numbers:
            self.stdout.write(
                self.style.WARNING(
                    "Provider match-number check: no explicit provider match-number field was found "
                    "in the normalized fixture payloads. Mapping still used kickoff time + team names only."
                )
            )

        if options["commit"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Done. Created {created}, updated {updated}, skipped {skipped}."
                )
            )
        else:
            self.stdout.write("Dry-run complete.")


def best_candidate(
    fixture: NormalizedFixture,
    local_matches: list[Match],
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


def _fixture_pair_label(fixture: NormalizedFixture) -> str:
    home = fixture.home_team.name if fixture.home_team else "TBD"
    away = fixture.away_team.name if fixture.away_team else "TBD"
    return f"{home} vs {away}"


def _format_unmapped(fixture: NormalizedFixture, reason: str) -> str:
    return (
        f"UNMAPPED: {fixture.provider_fixture_id} | {_fixture_pair_label(fixture)} | "
        f"{fixture.starting_at or '—'} | {reason}"
    )


def _local_match_number(match: Match) -> int | None:
    try:
        if match.match_number is None:
            return None
        return int(match.match_number)
    except (TypeError, ValueError):
        return None


def _match_number_note(fixture: NormalizedFixture, match: Match) -> str:
    provider_number = fixture.provider_match_number
    if provider_number is None:
        return ""

    local_number = _local_match_number(match)
    if local_number is None:
        return f"; provider_match_number={provider_number}; local match number unavailable"
    if local_number == provider_number:
        return f"; provider_match_number={provider_number} OK"
    return (
        f"; MATCH NUMBER MISMATCH provider={provider_number} "
        f"local={local_number}"
    )


def _mapping_notes(reason: str, match_number_note: str) -> str:
    if not match_number_note:
        return reason
    return f"{reason}{match_number_note}"


def _get_tournament(slug: str) -> Tournament:
    try:
        return Tournament.objects.get(slug=slug)
    except Tournament.DoesNotExist as exc:
        raise CommandError(f"Tournament not found: {slug}") from exc


def _resolve_date_range(tournament: Tournament, options: dict) -> tuple[str, str]:
    if options.get("date") and (options.get("start_date") or options.get("end_date")):
        raise CommandError("Use either --date or --start-date/--end-date, not both.")
    if options.get("date"):
        return options["date"], options["date"]
    if options.get("start_date") and options.get("end_date"):
        return options["start_date"], options["end_date"]
    if options.get("start_date") or options.get("end_date"):
        raise CommandError("Provide both --start-date and --end-date.")

    dates = Match.objects.filter(tournament=tournament, match_date__isnull=False).aggregate(
        start=Min("match_date"),
        end=Max("match_date"),
    )
    if not dates["start"] or not dates["end"]:
        raise CommandError(
            "Could not infer a date range from local matches. Provide --date or --start-date/--end-date."
        )
    return dates["start"].isoformat(), dates["end"].isoformat()


def _fetch_provider_payload(
    client,
    options: dict,
    start_date: str,
    end_date: str,
):
    kwargs = {
        "league_id": options.get("league_id"),
        "season": options.get("season"),
        "timezone": options.get("timezone"),
    }
    if start_date == end_date:
        return client.fixtures_by_date(start_date, **kwargs)
    return client.fixtures_between(start_date, end_date, **kwargs)
