from __future__ import annotations

import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from live_scores.providers import (
    LiveScoreProviderConfigurationError,
    LiveScoreProviderError,
    normalize_provider,
    provider_label,
)
from live_scores.worker import (
    due_fixture_ids_for_status_check,
    live_state_fixture_ids_for_status_check,
    poll_fixture_details_once,
    poll_live_scores_once,
    polling_decision_status,
)
from tournaments.models import Tournament


class Command(BaseCommand):
    help = "Poll the configured live-score provider and update mapped LiveMatchState rows."

    def add_arguments(self, parser):
        parser.add_argument(
            "tournament_slug",
            help="Tournament slug, e.g. fifa-world-cup-2026.",
        )
        parser.add_argument(
            "--provider",
            default=None,
            help="Provider to poll. Defaults to LIVE_SCORES_PROVIDER.",
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
            dest="provider_timezone",
            default=None,
            help="Optional provider timezone parameter, e.g. America/Chicago.",
        )
        parser.add_argument(
            "--once",
            action="store_true",
            help="Run one polling decision and exit.",
        )
        parser.add_argument(
            "--force-poll",
            action="store_true",
            help=(
                "Poll the provider live-fixtures endpoint even if the local schedule is outside "
                "the kickoff buffer. Useful for smoke tests."
            ),
        )
        parser.add_argument(
            "--no-apply-final-results",
            action="store_true",
            help=(
                "Do not commit provider-final fixtures into Match.home_score/away_score. "
                "LiveMatchState rows are still updated."
            ),
        )
        parser.add_argument(
            "--poll-interval",
            type=float,
            default=None,
            help="Seconds between provider polls while a game is live/near kickoff. Defaults to settings.",
        )
        parser.add_argument(
            "--idle-sleep",
            type=float,
            default=None,
            help="Seconds to sleep between low-frequency fixture-detail checks. Defaults to settings.",
        )
        parser.add_argument(
            "--kickoff-buffer-minutes",
            type=int,
            default=None,
            help="Start fast polling this many minutes before the next kickoff. Defaults to settings.",
        )
        parser.add_argument(
            "--fixture-detail-batch-size",
            type=int,
            default=20,
            help="Max provider fixture ids per direct fixture-detail request. Defaults to 20.",
        )
        parser.add_argument(
            "--sleep-after-error",
            type=float,
            default=10.0,
            help="Seconds to sleep after a provider/database error. Defaults to 10.",
        )
        parser.add_argument(
            "--skip-startup-recovery",
            action="store_true",
            help=(
                "Skip the one-time startup recovery check for mapped fixtures whose kickoff "
                "time has already passed but are not final locally."
            ),
        )

    def handle(self, *args, **options):
        tournament = self._get_tournament(options["tournament_slug"])
        provider = normalize_provider(options.get("provider"))
        once = options["once"]
        force_poll = options["force_poll"]
        apply_final_results = not options["no_apply_final_results"]
        poll_interval = options["poll_interval"]
        if poll_interval is None:
            poll_interval = getattr(settings, "LIVE_SCORES_POLL_INTERVAL_SECONDS", 15)
        idle_sleep = options["idle_sleep"]
        if idle_sleep is None:
            idle_sleep = getattr(settings, "LIVE_SCORES_IDLE_SLEEP_SECONDS", 300)
        sleep_after_error = options["sleep_after_error"]
        kickoff_buffer_minutes = options.get("kickoff_buffer_minutes")
        fixture_detail_batch_size = options["fixture_detail_batch_size"]
        provider_timezone = options.get("provider_timezone")

        # Startup safety: force the first loop to check the provider's live feed
        # immediately. This catches a worker restart that happens after kickoff.
        startup_live_check_pending = True
        has_live_games = False
        tracked_live_fixture_ids: set[str] = set()

        def log(message: str) -> None:
            self.stdout.write(f"[{timezone.now().isoformat()}] {message}")
            self.stdout.flush()

        log(
            f"Starting live-score worker for {tournament} using {provider_label(provider)}. "
            f"poll_interval={poll_interval}s, idle_sleep={idle_sleep}s, "
            f"kickoff_buffer={kickoff_buffer_minutes or getattr(settings, 'LIVE_SCORES_KICKOFF_BUFFER_MINUTES', 15)}m, "
            f"force_poll={force_poll}, apply_final_results={apply_final_results}."
        )

        if not options["skip_startup_recovery"]:
            try:
                recovery_fixture_ids = due_fixture_ids_for_status_check(
                    tournament=tournament,
                    provider=provider,
                )
                if recovery_fixture_ids:
                    log(
                        "Startup recovery check: confirming "
                        f"{len(recovery_fixture_ids)} mapped fixture(s) whose kickoff time "
                        "has passed but are not final locally."
                    )
                    recovery_result = poll_fixture_details_once(
                        fixture_ids=recovery_fixture_ids,
                        provider=provider,
                        tournament=tournament,
                        provider_timezone=provider_timezone,
                        batch_size=fixture_detail_batch_size,
                        apply_final_results=apply_final_results,
                        log=log,
                    )
                    log(recovery_result.summary())
                    tracked_live_fixture_ids.update(recovery_result.live_provider_fixture_ids)
                    has_live_games = recovery_result.has_live_games
                else:
                    log("Startup recovery check: no past, non-final mapped fixtures to verify.")
            except (LiveScoreProviderConfigurationError, LiveScoreProviderError) as exc:
                self.stderr.write(self.style.ERROR(f"Live-score provider error during startup recovery: {exc}"))
                if once:
                    raise CommandError(str(exc)) from exc
                time.sleep(sleep_after_error)
            except Exception as exc:  # noqa: BLE001 - keep long-running worker alive.
                self.stderr.write(self.style.ERROR(f"Live-score worker error during startup recovery: {exc}"))
                if once:
                    raise
                time.sleep(sleep_after_error)
        else:
            log("Startup recovery check skipped by --skip-startup-recovery.")

        while True:
            decision = polling_decision_status(
                tournament=tournament,
                provider=provider,
                has_live_games=has_live_games,
                kickoff_buffer_minutes=kickoff_buffer_minutes,
            )
            should_poll_live = force_poll or startup_live_check_pending or decision.should_poll_live

            try:
                if should_poll_live:
                    was_startup_check = startup_live_check_pending
                    if force_poll:
                        log("Force polling live fixtures.")
                    elif was_startup_check:
                        log("Startup safety check: polling live fixtures immediately.")
                    else:
                        log(decision.reason)
                    result = poll_live_scores_once(
                        provider=provider,
                        tournament=tournament,
                        league_id=options.get("league_id"),
                        season=options.get("season"),
                        status_codes=options.get("status_codes"),
                        provider_timezone=provider_timezone,
                        apply_final_results=apply_final_results,
                        log=log,
                    )
                    if was_startup_check:
                        startup_live_check_pending = False
                    log(result.summary())

                    tracked_live_fixture_ids.update(result.live_provider_fixture_ids)
                    tracked_live_fixture_ids.difference_update(result.final_provider_fixture_ids)
                    has_live_games = result.has_live_games

                    if result.total_provider_fixtures == 0:
                        # A one-shot command or restarted worker has an empty in-memory
                        # tracked_live_fixture_ids set. Recover candidates from the DB
                        # before concluding that there is nothing left to confirm.
                        confirmation_ids = set(tracked_live_fixture_ids)
                        confirmation_ids.update(
                            live_state_fixture_ids_for_status_check(
                                tournament=tournament,
                                provider=provider,
                            )
                        )
                        confirmation_ids.update(
                            due_fixture_ids_for_status_check(
                                tournament=tournament,
                                provider=provider,
                            )
                        )

                        if confirmation_ids:
                            log(
                                "Live feed returned no fixtures; confirming candidate fixture(s) "
                                "through direct fixture-detail lookup."
                            )
                            details_result = poll_fixture_details_once(
                                fixture_ids=sorted(confirmation_ids),
                                provider=provider,
                                tournament=tournament,
                                provider_timezone=provider_timezone,
                                batch_size=fixture_detail_batch_size,
                                apply_final_results=apply_final_results,
                                log=log,
                            )
                            log(details_result.summary())
                            tracked_live_fixture_ids = set(details_result.live_provider_fixture_ids)
                            has_live_games = details_result.has_live_games

                    sleep_seconds = poll_interval

                else:
                    log(decision.reason)
                    due_fixture_ids = due_fixture_ids_for_status_check(
                        tournament=tournament,
                        provider=provider,
                    )
                    if due_fixture_ids:
                        log(
                            f"Idle status check for {len(due_fixture_ids)} mapped fixture(s) "
                            "whose kickoff time has passed."
                        )
                        details_result = poll_fixture_details_once(
                            fixture_ids=due_fixture_ids,
                            provider=provider,
                            tournament=tournament,
                            provider_timezone=provider_timezone,
                            batch_size=fixture_detail_batch_size,
                            apply_final_results=apply_final_results,
                            log=log,
                        )
                        log(details_result.summary())
                        tracked_live_fixture_ids = set(details_result.live_provider_fixture_ids)
                        has_live_games = details_result.has_live_games
                    else:
                        has_live_games = False
                        tracked_live_fixture_ids.clear()
                    sleep_seconds = idle_sleep

            except (LiveScoreProviderConfigurationError, LiveScoreProviderError) as exc:
                self.stderr.write(self.style.ERROR(f"Live-score provider error: {exc}"))
                if once:
                    raise CommandError(str(exc)) from exc
                time.sleep(sleep_after_error)
                continue
            except Exception as exc:  # noqa: BLE001 - keep long-running worker alive.
                self.stderr.write(self.style.ERROR(f"Live-score worker error: {exc}"))
                if once:
                    raise
                time.sleep(sleep_after_error)
                continue

            if once:
                return
            time.sleep(sleep_seconds)

    @staticmethod
    def _get_tournament(slug: str) -> Tournament:
        try:
            return Tournament.objects.get(slug=slug)
        except Tournament.DoesNotExist as exc:
            raise CommandError(f"Tournament not found: {slug}") from exc
