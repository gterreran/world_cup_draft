from django.core.management.base import BaseCommand
from django.utils.text import slugify

from tournaments.models import NationalTeam, Tournament, TeamTournamentStatus


DEMO_TEAMS = {
    1: [
        "Argentina", "France", "Spain", "England",
        "Brazil", "Portugal", "Netherlands", "Belgium",
        "Germany", "Italy", "Uruguay", "Croatia",
    ],
    2: [
        "Mexico", "United States", "Colombia", "Morocco",
        "Switzerland", "Japan", "Senegal", "Denmark",
        "Austria", "Iran", "South Korea", "Australia",
    ],
    3: [
        "Canada", "Serbia", "Poland", "Ecuador",
        "Turkey", "Ukraine", "Panama", "Egypt",
        "Algeria", "Norway", "Sweden", "Wales",
    ],
    4: [
        "Costa Rica", "Jamaica", "New Zealand", "South Africa",
        "Qatar", "Saudi Arabia", "Iraq", "Uzbekistan",
        "Bolivia", "Venezuela", "Honduras", "Ghana",
    ],
}


class Command(BaseCommand):
    help = "Seed a demo 2026 World Cup tournament with 48 placeholder teams."

    def handle(self, *args, **options):
        tournament, created = Tournament.objects.get_or_create(
            slug="fifa-world-cup-2026-demo",
            defaults={
                "name": "FIFA World Cup",
                "year": 2026,
                "host": "Canada, Mexico, United States",
                "status": Tournament.Status.UPCOMING,
            },
        )

        created_count = 0
        updated_count = 0

        for pot, teams in DEMO_TEAMS.items():
            for rank_in_pot, team_name in enumerate(teams, start=1):
                fifa_code = _code_from_name(team_name)

                team, was_created = NationalTeam.objects.update_or_create(
                    tournament=tournament,
                    fifa_code=fifa_code,
                    defaults={
                        "name": team_name,
                        "pot": pot,
                        "fifa_rank": ((pot - 1) * 12) + rank_in_pot,
                    },
                )

                TeamTournamentStatus.objects.get_or_create(
                    tournament=tournament,
                    team=team,
                )

                if was_created:
                    created_count += 1
                else:
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {tournament}: {created_count} created, {updated_count} updated."
            )
        )


def _code_from_name(name: str) -> str:
    special = {
        "United States": "USA",
        "South Korea": "KOR",
        "Costa Rica": "CRC",
        "New Zealand": "NZL",
        "South Africa": "RSA",
        "Saudi Arabia": "KSA",
        "Iraq": "IRQ",
        "Austria": "AUT",
    }

    if name in special:
        return special[name]

    compact = slugify(name).replace("-", "").upper()
    return compact[:3]