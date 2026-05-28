from tournaments.models import Match

from tournaments.standings import compute_group_standings
from tournaments.qualification import compute_qualification
from tournaments.qualification_status import compute_group_qualification_status
from django.db import models

def build_group_stage_context(tournament):
    standings_by_group = compute_group_standings(tournament)
    qualification = compute_qualification(tournament)

    qualified_team_ids = {
        team.id
        for team in qualification.slot_map.values()
    }

    best_third_team_ids = {
        standing.team.id
        for standing in qualification.best_third_place_teams
    }

    output = []


    qualification_status = compute_group_qualification_status(tournament)

    for group_name, standings in standings_by_group.items():
        matches = (
            Match.objects.filter(
                tournament=tournament,
                stage=Match.Stage.GROUP,
            ).filter(
                models.Q(group=group_name)
                | models.Q(home_team__group=group_name)
                | models.Q(away_team__group=group_name)
            )
            .select_related("home_team", "away_team")
            .order_by("kickoff_time", "match_number")
        )

        rows = []

        for row in standings:
            team_status = qualification_status.get(row.team.id, {})

            qualification_label = team_status.get("label", "")
            qualification_class = team_status.get("class", "")

            rows.append(
                {
                    "standing": row,
                    "qualification_label": qualification_label,
                    "qualification_class": qualification_class,
                }
            )

        output.append(
            {
                "name": group_name,
                "standings": rows,
                "matches": matches,
            }
        )

    return output
