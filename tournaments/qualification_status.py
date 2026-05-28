from tournaments.models import Match
from tournaments.mathematical_status import compute_mathematical_status


def compute_group_qualification_status(tournament):
    """Return qualification/elimination labels for the group-stage page.

    The status is computed live so the page reflects the current set of
    results immediately. Persisted TeamTournamentStatus rows are still used for
    advanced_from_group, but mathematical Q/E comes from the current simulator.
    """
    status = {}

    mathematical_status_map = compute_mathematical_status(tournament)

    matches = (
        Match.objects.filter(
            tournament=tournament,
            stage=Match.Stage.GROUP,
        )
        .select_related("home_team", "away_team")
    )

    for match in matches:
        for team in [match.home_team, match.away_team]:
            if team is None:
                continue

            math_status = mathematical_status_map.get(team.id)

            advanced_from_group = False

            try:
                team_status = team.tournament_status
            except Exception:
                team_status = None

            if team_status is not None:
                advanced_from_group = team_status.advanced_from_group

            qualified = advanced_from_group
            eliminated = False
            guaranteed_position = None

            if math_status is not None:
                qualified = qualified or math_status.qualified
                eliminated = (
                    math_status.eliminated
                    and not advanced_from_group
                    and not math_status.qualified
                )
                guaranteed_position = math_status.guaranteed_position

            label = ""
            css_class = ""

            if qualified:
                label = _qualification_label(guaranteed_position)
                css_class = "qualified"
            elif eliminated:
                label = "E"
                css_class = "eliminated"

            status[team.id] = {
                "qualified": qualified,
                "eliminated": eliminated,
                "guaranteed_position": guaranteed_position,
                "label": label,
                "class": css_class,
            }

    return status


def _qualification_label(guaranteed_position: int | None) -> str:
    if guaranteed_position in {1, 2, 3}:
        return f"Q{guaranteed_position}"

    return "Q"
