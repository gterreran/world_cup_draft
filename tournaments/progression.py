from tournaments.bracket import populate_guaranteed_group_slots, populate_knockout_bracket
from tournaments.qualification import compute_qualification
from tournaments.status import recompute_team_statuses
from tournaments.models import Match


def recompute_tournament_progression(tournament):
    qualification = compute_qualification(tournament)

    if _all_group_stage_matches_complete(tournament):
        populate_knockout_bracket(tournament=tournament)
    else:
        populate_guaranteed_group_slots(tournament=tournament)

    recompute_team_statuses(
        tournament=tournament,
        qualification_result=qualification,
    )

def _all_group_stage_matches_complete(tournament) -> bool:
    group_matches = Match.objects.filter(
        tournament=tournament,
        stage=Match.Stage.GROUP,
    )

    if not group_matches.exists():
        return False

    return all(match.is_complete for match in group_matches)