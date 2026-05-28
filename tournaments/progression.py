from tournaments.bracket import populate_knockout_bracket
from tournaments.qualification import compute_qualification
from tournaments.status import recompute_team_statuses


def recompute_tournament_progression(tournament):
    qualification = compute_qualification(tournament)

    populate_knockout_bracket(
        tournament=tournament,
    )

    recompute_team_statuses(
        tournament=tournament,
        qualification_result=qualification,
    )