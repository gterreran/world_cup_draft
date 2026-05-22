def default_scoring_config() -> dict:
    return {
        "group_win": 3,
        "group_draw": 1,
        "group_loss": 0,
        "qualify_knockout": 3,
        "knockout_win_regulation": 4,
        "knockout_win_extra_time": 3,
        "knockout_win_penalties": 2,
        "knockout_loss_extra_time": 1,
        "knockout_loss_penalties": 1,
        "champion_bonus": 8,
        "runner_up_bonus": 5,
        "third_place_bonus": 3,
        "fourth_place_bonus": 2,
    }


TIEBREAKER_CHOICES = [
    ("teams_advanced", "Most teams advanced"),
    ("wins", "Most wins"),
    ("goal_difference", "Best goal difference"),
    ("goals_scored", "Most goals scored"),
    ("best_finish_rank", "Best single-team finish"),
]


def default_tiebreaker_config() -> list[str]:
    return [
        "teams_advanced",
        "wins",
        "goal_difference",
        "goals_scored",
        "best_finish_rank",
    ]