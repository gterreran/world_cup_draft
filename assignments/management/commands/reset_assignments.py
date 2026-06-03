from django.core.management.base import BaseCommand, CommandError

from leagues.models import League
from assignments.services import reset_assignments


class Command(BaseCommand):
    help = "Reset all assigned national teams for a league."

    def add_arguments(self, parser):
        parser.add_argument("league_slug", help="Slug of the league to reset.")
        parser.add_argument(
            "--unlock",
            action="store_true",
            help="Unlock the league setup after clearing assignments.",
        )

    def handle(self, *args, **options):
        league_slug = options["league_slug"]

        try:
            league = League.objects.get(slug=league_slug)
        except League.DoesNotExist as exc:
            raise CommandError(f"League not found: {league_slug}") from exc

        deleted_count = reset_assignments(
            league,
            unlock=options["unlock"],
        )

        lock_message = "unlocked setup" if options["unlock"] else "kept setup locked"

        self.stdout.write(
            self.style.SUCCESS(
                f"Reset assignments for {league.name}. "
                f"Deleted {deleted_count} assignment object(s), "
                f"{lock_message}, and reset the draft."
            )
        )
