from __future__ import annotations

import json

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
    help = "Inspect live fixture payloads from the active live-score provider without writing to the database."

    def add_arguments(self, parser):
        parser.add_argument(
            "--provider",
            default=None,
            help="Provider to inspect. Defaults to LIVE_SCORES_PROVIDER.",
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
            "--status-codes",
            default=None,
            help="Provider status filter for live fixtures. Defaults to configured live status codes.",
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
        try:
            provider = normalize_provider(options.get("provider"))
            client = get_provider_client(provider)
            payload = client.live_fixtures(
                league_id=options.get("league_id"),
                season=options.get("season"),
                status_codes=options.get("status_codes"),
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

        self.stdout.write(f"{provider_label(provider)} returned {len(raw_fixtures)} live fixture(s).")
        if not fixtures:
            return

        for fixture in fixtures:
            home = fixture.home_team.name if fixture.home_team else "TBD"
            away = fixture.away_team.name if fixture.away_team else "TBD"
            minute = f" {fixture.minute}'" if fixture.minute is not None else ""
            match_number = (
                f"match_no={fixture.provider_match_number}"
                if fixture.provider_match_number is not None
                else "match_no=—"
            )
            self.stdout.write(
                f"{fixture.provider_fixture_id} | {home} {fixture.score_label} {away} | "
                f"{fixture.status}{minute} | {fixture.state_code or '—'} | "
                f"{fixture.starting_at or '—'} | {match_number}"
            )
