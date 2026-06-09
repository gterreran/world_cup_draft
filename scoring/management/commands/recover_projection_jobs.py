from __future__ import annotations

from django.core.management.base import BaseCommand
from django.utils import timezone

from scoring.models import ProjectionJobState


class Command(BaseCommand):
    help = "Mark stale running projection jobs as failed/recoverable."

    def add_arguments(self, parser):
        parser.add_argument(
            "--all-running",
            action="store_true",
            help="Recover every running projection job, even if its heartbeat is not stale.",
        )
        parser.add_argument(
            "--league",
            help="Optional league slug. If omitted, all projection job states are considered.",
        )

    def handle(self, *args, **options):
        queryset = ProjectionJobState.objects.select_related("league").filter(
            status=ProjectionJobState.Status.RUNNING,
        )

        league_slug = options.get("league")
        if league_slug:
            queryset = queryset.filter(league__slug=league_slug)

        recovered = 0
        for state in queryset:
            if not options["all_running"] and not state.is_running_stale():
                self.stdout.write(
                    f"Skipping active job for {state.league.slug}: heartbeat is still recent."
                )
                continue

            state.status = ProjectionJobState.Status.FAILED
            state.finished_at = timezone.now()
            state.error_message = "Recovered stale running projection job."
            state.save(update_fields=["status", "finished_at", "error_message", "updated_at"])
            recovered += 1
            self.stdout.write(self.style.WARNING(f"Recovered stale job for {state.league.slug}."))

        if recovered == 0:
            self.stdout.write("No stale running projection jobs recovered.")
        else:
            self.stdout.write(self.style.SUCCESS(f"Recovered {recovered} projection job(s)."))
