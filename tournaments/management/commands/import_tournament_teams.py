import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from tournaments.models import NationalTeam, TeamTournamentStatus, Tournament


class Command(BaseCommand):
    help = "Import tournament teams from a JSON file."

    def add_arguments(self, parser):
        parser.add_argument(
            "json_path",
            type=str,
            help="Path to the tournament teams JSON file.",
        )

    def handle(self, *args, **options):
        json_path = Path(options["json_path"])

        if not json_path.exists():
            raise CommandError(f"File does not exist: {json_path}")

        with json_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        tournament_data = payload["tournament"]
        team_rows = payload["teams"]

        tournament, _ = Tournament.objects.update_or_create(
            slug=tournament_data["slug"],
            defaults={
                "name": tournament_data["name"],
                "year": tournament_data["year"],
                "host": tournament_data.get("host", ""),
                "status": tournament_data.get("status", Tournament.Status.UPCOMING),
            },
        )

        created_count = 0
        updated_count = 0

        for row in team_rows:
            team, created = NationalTeam.objects.update_or_create(
                tournament=tournament,
                fifa_code=row["fifa_code"],
                defaults={
                    "name": row["name"],
                    "iso2_code": row.get("iso2_code", ""),
                    "flag": row.get("flag") or "🏳️",
                    "confederation": row.get("confederation", ""),
                    "pot": row.get("pot"),
                    "fifa_rank": row.get("fifa_rank"),
                    "group": row.get("group", ""),
                },
            )

            TeamTournamentStatus.objects.get_or_create(
                tournament=tournament,
                team=team,
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Imported {tournament}: {created_count} created, {updated_count} updated."
            )
        )