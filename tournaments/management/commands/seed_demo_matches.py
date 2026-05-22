from django.core.management.base import BaseCommand

from tournaments.models import Match, NationalTeam, TeamTournamentStatus, Tournament


GROUP_MATCHES = [
    ("Argentina", "Canada", 2, 0),
    ("France", "Costa Rica", 3, 1),
    ("Spain", "Jamaica", 1, 1),
    ("England", "New Zealand", 2, 1),
    ("Brazil", "South Africa", 4, 0),
    ("Portugal", "Qatar", 2, 2),
    ("Netherlands", "Saudi Arabia", 1, 0),
    ("Belgium", "Iraq", 0, 1),
    ("Germany", "Uzbekistan", 3, 0),
    ("Italy", "Bolivia", 1, 2),
    ("Uruguay", "Venezuela", 2, 0),
    ("Croatia", "Ghana", 1, 1),
]


KNOCKOUT_MATCHES = [
    # Round of 32
    (Match.Stage.ROUND_OF_32, "Argentina", "Costa Rica", 2, 0, False, False, "Argentina"),
    (Match.Stage.ROUND_OF_32, "France", "Canada", 1, 1, True, True, "France"),
    (Match.Stage.ROUND_OF_32, "Brazil", "Jamaica", 3, 0, False, False, "Brazil"),
    (Match.Stage.ROUND_OF_32, "England", "New Zealand", 2, 1, True, False, "England"),
    (Match.Stage.ROUND_OF_32, "Germany", "Iraq", 1, 0, False, False, "Germany"),
    (Match.Stage.ROUND_OF_32, "Netherlands", "Saudi Arabia", 2, 2, True, True, "Netherlands"),
    (Match.Stage.ROUND_OF_32, "Spain", "Ghana", 1, 0, False, False, "Spain"),
    (Match.Stage.ROUND_OF_32, "Uruguay", "Venezuela", 2, 1, False, False, "Uruguay"),

    # Round of 16
    (Match.Stage.ROUND_OF_16, "Argentina", "France", 1, 1, True, True, "Argentina"),
    (Match.Stage.ROUND_OF_16, "Brazil", "England", 2, 1, False, False, "Brazil"),
    (Match.Stage.ROUND_OF_16, "Germany", "Netherlands", 1, 0, True, False, "Germany"),
    (Match.Stage.ROUND_OF_16, "Uruguay", "Spain", 0, 0, True, True, "Spain"),

    # Quarterfinals
    (Match.Stage.QUARTERFINAL, "Argentina", "Brazil", 2, 1, False, False, "Argentina"),
    (Match.Stage.QUARTERFINAL, "Germany", "Spain", 1, 2, True, False, "Spain"),

    # Final
    (Match.Stage.FINAL, "Argentina", "Spain", 3, 2, False, False, "Argentina"),
]


class Command(BaseCommand):
    help = "Seed demo match results for the demo 2026 World Cup tournament."

    def handle(self, *args, **options):
        tournament = Tournament.objects.get(slug="fifa-world-cup-2026-demo")

        created_count = 0
        updated_count = 0

        for home, away, home_score, away_score in GROUP_MATCHES:
            was_created = _upsert_match(
                tournament=tournament,
                stage=Match.Stage.GROUP,
                home_name=home,
                away_name=away,
                home_score=home_score,
                away_score=away_score,
                went_to_extra_time=False,
                went_to_penalties=False,
                winner_name=None,
            )

            if was_created:
                created_count += 1
            else:
                updated_count += 1

        for match_data in KNOCKOUT_MATCHES:
            stage, home, away, home_score, away_score, went_et, went_pens, winner = match_data

            was_created = _upsert_match(
                tournament=tournament,
                stage=stage,
                home_name=home,
                away_name=away,
                home_score=home_score,
                away_score=away_score,
                went_to_extra_time=went_et,
                went_to_penalties=went_pens,
                winner_name=winner,
            )

            if was_created:
                created_count += 1
            else:
                updated_count += 1

        _set_demo_statuses(tournament)

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded demo matches: {created_count} created, {updated_count} updated."
            )
        )


def _upsert_match(
    *,
    tournament: Tournament,
    stage: str,
    home_name: str,
    away_name: str,
    home_score: int,
    away_score: int,
    went_to_extra_time: bool,
    went_to_penalties: bool,
    winner_name: str | None,
) -> bool:
    home_team = NationalTeam.objects.get(tournament=tournament, name=home_name)
    away_team = NationalTeam.objects.get(tournament=tournament, name=away_name)

    winner = None
    if winner_name is not None:
        winner = NationalTeam.objects.get(tournament=tournament, name=winner_name)

    _, was_created = Match.objects.update_or_create(
        tournament=tournament,
        stage=stage,
        home_team=home_team,
        away_team=away_team,
        defaults={
            "home_score": home_score,
            "away_score": away_score,
            "went_to_extra_time": went_to_extra_time,
            "went_to_penalties": went_to_penalties,
            "winner": winner,
        },
    )

    return was_created

def _set_demo_statuses(tournament: Tournament) -> None:
    advanced_teams = {
        "Argentina", "France", "Brazil", "England",
        "Germany", "Netherlands", "Spain", "Uruguay",
        "Costa Rica", "Canada", "Jamaica", "New Zealand",
        "Iraq", "Saudi Arabia", "Ghana", "Venezuela",
    }

    finish_ranks = {
        "Argentina": 1,
        "Spain": 2,
        "Brazil": 3,
        "Germany": 4,
    }

    eliminated_stages = {
        "Argentina": TeamTournamentStatus.EliminationStage.CHAMPION,
        "Spain": TeamTournamentStatus.EliminationStage.FINAL,
        "Brazil": TeamTournamentStatus.EliminationStage.SEMIFINAL,
        "Germany": TeamTournamentStatus.EliminationStage.SEMIFINAL,
        "France": TeamTournamentStatus.EliminationStage.ROUND_OF_16,
        "England": TeamTournamentStatus.EliminationStage.ROUND_OF_16,
        "Netherlands": TeamTournamentStatus.EliminationStage.ROUND_OF_16,
        "Uruguay": TeamTournamentStatus.EliminationStage.ROUND_OF_16,
        "Costa Rica": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
        "Canada": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
        "Jamaica": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
        "New Zealand": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
        "Iraq": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
        "Saudi Arabia": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
        "Ghana": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
        "Venezuela": TeamTournamentStatus.EliminationStage.ROUND_OF_32,
    }

    for team in NationalTeam.objects.filter(tournament=tournament):
        status, _ = TeamTournamentStatus.objects.get_or_create(
            tournament=tournament,
            team=team,
        )

        status.advanced_from_group = team.name in advanced_teams
        status.finish_rank = finish_ranks.get(team.name)
        status.eliminated_stage = eliminated_stages.get(
            team.name,
            TeamTournamentStatus.EliminationStage.GROUP,
        )
        status.save()