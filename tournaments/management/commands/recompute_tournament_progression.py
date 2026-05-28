from django.core.management.base import BaseCommand, CommandError

from tournaments.models import Tournament
from tournaments.progression import recompute_tournament_progression


class Command(BaseCommand):
    help = "Recompute tournament progression and populate knockout bracket."

    def add_arguments(self, parser):
        parser.add_argument("tournament_slug", type=str)

    def handle(self, *args, **options):
        slug = options["tournament_slug"]

        try:
            tournament = Tournament.objects.get(slug=slug)
        except Tournament.DoesNotExist as exc:
            raise CommandError(f"Tournament does not exist: {slug}") from exc

        recompute_tournament_progression(tournament)

        self.stdout.write(
            self.style.SUCCESS(
                f"Recomputed tournament progression for {tournament}."
            )
        )