from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from leagues.models import League
from scoring.services import recompute_league_standings
from tournaments.models import Match, NationalTeam, TeamTournamentStatus, Tournament


class Command(BaseCommand):
    help = "Reset all scores, knockout teams, and tournament statuses."

    def add_arguments(self, parser):
        parser.add_argument("tournament_slug", type=str)
        parser.add_argument(
            "--keep-knockout-teams",
            action="store_true",
            help="Reset scores/statuses but keep populated knockout participants.",
        )

    def handle(self, *args, **options):
        slug = options["tournament_slug"]
        keep_knockout_teams = options["keep_knockout_teams"]

        try:
            tournament = Tournament.objects.get(slug=slug)
        except Tournament.DoesNotExist as exc:
            raise CommandError(f"Tournament does not exist: {slug}") from exc

        with transaction.atomic():
            matches = Match.objects.filter(tournament=tournament)

            for match in matches.select_related("home_team", "away_team"):
                match.status = Match.Status.SCHEDULED
                match.home_score = None
                match.away_score = None
                match.went_to_extra_time = False
                match.went_to_penalties = False
                match.winner = None

                if match.stage != Match.Stage.GROUP and not keep_knockout_teams:
                    match.home_team = None
                    match.away_team = None

                match.save()

            TeamTournamentStatus.objects.filter(tournament=tournament).delete()

            for team in NationalTeam.objects.filter(tournament=tournament):
                TeamTournamentStatus.objects.create(
                    tournament=tournament,
                    team=team,
                    advanced_from_group=False,
                    mathematically_qualified=False,
                    mathematically_eliminated=False,
                    eliminated_stage="",
                    finish_rank=None,
                )

            for league in League.objects.filter(tournament=tournament):
                recompute_league_standings(league)

        self.stdout.write(
            self.style.SUCCESS(
                f"Reset scores and tournament state for {tournament}."
            )
        )
