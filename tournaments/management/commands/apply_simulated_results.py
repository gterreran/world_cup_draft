import json
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from leagues.models import League
from scoring.services import recompute_league_standings
from tournaments.models import Match, Tournament
from tournaments.progression import recompute_tournament_progression


class Command(BaseCommand):
    help = "Apply simulated tournament results one match at a time."

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Path to the simulated results JSON file.",
        )
        parser.add_argument(
            "--from-match",
            type=int,
            default=None,
            help="First match number to apply.",
        )
        parser.add_argument(
            "--to-match",
            type=int,
            default=None,
            help="Last match number to apply.",
        )
        parser.add_argument(
            "--pause",
            type=float,
            default=0.0,
            help="Optional pause in seconds after each applied match.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would be applied without saving changes.",
        )

    def handle(self, *args, **options):
        json_path = Path(options["json_path"])

        if not json_path.exists():
            raise CommandError(f"File does not exist: {json_path}")

        with json_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        tournament_slug = payload["tournament_slug"]
        results = payload["results"]

        try:
            tournament = Tournament.objects.get(slug=tournament_slug)
        except Tournament.DoesNotExist as exc:
            raise CommandError(f"Tournament does not exist: {tournament_slug}") from exc

        from_match = options["from_match"]
        to_match = options["to_match"]
        pause = options["pause"]
        dry_run = options["dry_run"]

        results = sorted(results, key=lambda row: row["match_number"])

        applied_count = 0

        for row in results:
            match_number = row["match_number"]

            if from_match is not None and match_number < from_match:
                continue

            if to_match is not None and match_number > to_match:
                continue

            if dry_run:
                self.stdout.write(
                    f"Would apply Match {match_number}: "
                    f"{row['home_score']}-{row['away_score']}"
                )
                continue

            with transaction.atomic():
                # Recompute before each match so knockout participants are populated
                # from previous results before we try to assign a knockout winner.
                recompute_tournament_progression(tournament)

                match = Match.objects.select_for_update().get(
                    tournament=tournament,
                    match_number=match_number,
                )

                self._apply_result(match, row)
                match.save()

                recompute_tournament_progression(tournament)
                self._recompute_related_leagues(tournament)

            applied_count += 1

            self.stdout.write(
                self.style.SUCCESS(
                    f"Applied Match {match.match_number}: "
                    f"{match.home_label} {match.home_score}–{match.away_score} "
                    f"{match.away_label}"
                )
            )

            if pause > 0:
                time.sleep(pause)

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run complete. No changes saved."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Applied {applied_count} simulated result(s) for {tournament}."
                )
            )

    def _apply_result(self, match: Match, row: dict) -> None:
        if match.stage != Match.Stage.GROUP and (
            match.home_team_id is None or match.away_team_id is None
        ):
            raise CommandError(
                f"Match {match.match_number} is a knockout match but does not "
                "have both teams populated yet. Check bracket progression."
            )

        match.home_score = row["home_score"]
        match.away_score = row["away_score"]
        match.status = row.get("status", Match.Status.FINAL)
        match.went_to_extra_time = row.get("went_to_extra_time", False)
        match.went_to_penalties = row.get("went_to_penalties", False)

        if match.stage == Match.Stage.GROUP:
            match.winner = None
            match.went_to_extra_time = False
            match.went_to_penalties = False
            return

        winner_side = row.get("winner_side")

        if winner_side == "home":
            match.winner = match.home_team
        elif winner_side == "away":
            match.winner = match.away_team
        else:
            raise CommandError(
                f"Knockout match {match.match_number} requires winner_side "
                "to be 'home' or 'away'."
            )

    def _recompute_related_leagues(self, tournament: Tournament) -> None:
        for league in League.objects.filter(tournament=tournament):
            recompute_league_standings(league)
