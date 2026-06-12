from __future__ import annotations

import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from live_scores.providers import (
    LiveScoreProviderConfigurationError,
    LiveScoreProviderError,
    extract_fixture_list,
    get_provider_client,
    normalize_provider,
    provider_label,
)


class Command(BaseCommand):
    help = "Inspect provider fixture payloads by date/range without writing to the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            default=None,
            help="Provider to inspect. Defaults to LIVE_SCORES_PROVIDER.",
        )
        parser.add_argument(
            "--date",
            help="Single date to inspect, YYYY-MM-DD.",
        )
        parser.add_argument(
            "--start-date",
            help="Start date, YYYY-MM-DD. Must be used with --end-date.",
        )
        parser.add_argument(
            "--end-date",
            help="End date, YYYY-MM-DD. Must be used with --start-date.",
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
            "--raw",
            action="store_true",
            help="Print raw JSON instead of normalized fixture summaries.",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Limit normalized fixture rows printed. 0 means no limit.",
        )

    def handle(self, *args, **options):
        start_date, end_date = _resolve_date_range(options)

        try:
            provider = normalize_provider(options.get("provider"))
            client = get_provider_client(provider)
            if start_date == end_date:
                payload = client.fixtures_by_date(
                    start_date,
                    league_id=options.get("league_id"),
                    season=options.get("season"),
                    timezone=options.get("timezone"),
                )
            else:
                payload = client.fixtures_between(
                    start_date,
                    end_date,
                    league_id=options.get("league_id"),
                    season=options.get("season"),
                    timezone=options.get("timezone"),
                )
        except LiveScoreProviderConfigurationError as exc:
            raise CommandError(str(exc)) from exc
        except LiveScoreProviderError as exc:
            raise CommandError(str(exc)) from exc

        if options["raw"]:
            self.stdout.write(json.dumps(payload, indent=2, sort_keys=True, default=str))
            return

        raw_fixtures = extract_fixture_list(payload)
        fixtures = [client.normalize_fixture(raw) for raw in raw_fixtures]
        if options["limit"]:
            fixtures = fixtures[: options["limit"]]

        self.stdout.write(
            f"{provider_label(provider)} returned {len(raw_fixtures)} fixture(s) for {start_date} → {end_date}."
        )
        if not fixtures:
            return

        for fixture in fixtures:
            home = fixture.home_team.name if fixture.home_team else "TBD"
            away = fixture.away_team.name if fixture.away_team else "TBD"
            match_number = (
                f"match_no={fixture.provider_match_number}"
                if fixture.provider_match_number is not None
                else "match_no=—"
            )
            self.stdout.write(
                f"{fixture.provider_fixture_id} | {home} vs {away} | "
                f"{fixture.starting_at or '—'} | {fixture.status} | {fixture.score_label} | {match_number}"
            )


def _resolve_date_range(options: dict) -> tuple[str, str]:
    if options.get("date") and (options.get("start_date") or options.get("end_date")):
        raise CommandError("Use either --date or --start-date/--end-date, not both.")
    if options.get("date"):
        return options["date"], options["date"]
    if options.get("start_date") and options.get("end_date"):
        return options["start_date"], options["end_date"]
    if options.get("start_date") or options.get("end_date"):
        raise CommandError("Provide both --start-date and --end-date.")

    today = date.today()
    return today.isoformat(), (today + timedelta(days=1)).isoformat()
