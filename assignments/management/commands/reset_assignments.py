from django.core.management.base import BaseCommand, CommandError

from leagues.models import League
from scoring.projections import mark_projection_entries_stale


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

        deleted_count, _ = league.team_assignments.all().delete()

        if hasattr(league, "draft_state"):
            league.draft_state.delete()

        league.assignments_generated_at = None

        if options["unlock"]:
            league.assignments_locked = False

        league.save(
            update_fields=[
                "assignments_generated_at",
                "assignments_locked",
            ]
            if options["unlock"]
            else ["assignments_generated_at"]
        )

        mark_projection_entries_stale(
            league,
            reason="Team assignments were reset.",
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Reset assignments for {league.name}. "
                f"Deleted {deleted_count} assignment object(s)."
            )
        )