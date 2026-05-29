from django.core.management.base import BaseCommand, CommandError

from leagues.models import League
from scoring.projections import recompute_projection_entries


class Command(BaseCommand):
    help = "Recompute cached max-points projections for one league or all leagues."

    def add_arguments(self, parser):
        parser.add_argument(
            "slug",
            nargs="?",
            help="Optional league slug. If omitted, all leagues are recomputed.",
        )

    def handle(self, *args, **options):
        slug = options.get("slug")

        if slug:
            try:
                leagues = [League.objects.get(slug=slug)]
            except League.DoesNotExist as exc:
                raise CommandError(f"League not found: {slug}") from exc
        else:
            leagues = list(League.objects.all().order_by("slug"))

        if not leagues:
            self.stdout.write(self.style.WARNING("No leagues found."))
            return

        for league in leagues:
            self.stdout.write(f"Recomputing projections for {league.slug}...")
            recompute_projection_entries(league)
            self.stdout.write(self.style.SUCCESS(f"Done: {league.slug}"))
