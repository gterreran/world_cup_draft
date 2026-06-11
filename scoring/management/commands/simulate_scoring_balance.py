from __future__ import annotations

import math

from django.core.management.base import BaseCommand, CommandError

from leagues.models import League
from scoring.simulations import (
    SimulationConfigurationError,
    SimulationSettings,
    pct,
    simulate_league_forecast,
)


class Command(BaseCommand):
    help = "Simulate remaining tournaments to evaluate fantasy scoring balance."

    def add_arguments(self, parser):
        parser.add_argument("league_slug", help="League slug to simulate.")
        parser.add_argument(
            "--runs",
            type=int,
            default=1000,
            help="Number of tournaments to simulate. Default: 1000.",
        )
        parser.add_argument(
            "--mode",
            choices=("seeded", "uniform"),
            default="seeded",
            help="Outcome model. 'seeded' uses FIFA rank as an Elo proxy. Default: seeded.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=None,
            help="Optional random seed for reproducible simulations.",
        )
        parser.add_argument(
            "--draw-prob",
            type=float,
            default=0.24,
            help="Group-stage draw probability. Default: 0.24.",
        )
        parser.add_argument(
            "--rank-elo-step",
            type=float,
            default=8.0,
            help=(
                "Elo-point value of one FIFA-ranking place in seeded mode. "
                "Default: 8.0."
            ),
        )
        parser.add_argument(
            "--regulation-prob",
            type=float,
            default=0.75,
            help="Knockout decision probability in regulation. Default: 0.75.",
        )
        parser.add_argument(
            "--extra-time-prob",
            type=float,
            default=0.15,
            help="Knockout decision probability after extra time. Default: 0.15.",
        )
        parser.add_argument(
            "--top",
            type=int,
            default=12,
            help="Number of manager rows to print. Default: 12.",
        )

    def handle(self, *args, **options):
        try:
            league = League.objects.select_related("tournament").get(slug=options["league_slug"])
        except League.DoesNotExist as exc:
            raise CommandError(f"League not found: {options['league_slug']}") from exc

        settings = SimulationSettings(
            runs=options["runs"],
            mode=options["mode"],
            seed=options["seed"],
            draw_prob=options["draw_prob"],
            rank_elo_step=options["rank_elo_step"],
            regulation_prob=options["regulation_prob"],
            extra_time_prob=options["extra_time_prob"],
        )

        self.stdout.write(
            f"Simulating {settings.runs:,} tournaments for league={league.slug!r} "
            f"mode={settings.mode} seed={settings.seed}..."
        )

        try:
            result = simulate_league_forecast(
                league,
                settings=settings,
                progress_logger=self.stdout.write,
            )
        except SimulationConfigurationError as exc:
            raise CommandError(str(exc)) from exc

        metrics = result.metrics

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Scoring balance summary"))
        self.stdout.write(f"League: {league.name} ({league.slug})")
        self.stdout.write(f"Tournament: {league.tournament}")
        self.stdout.write(f"Runs: {result.runs:,}")
        self.stdout.write(f"Mode: {result.mode}")
        self.stdout.write("")
        self.stdout.write("Key metrics:")
        self.stdout.write(f"  Champion-owner win rate:      {pct(metrics.champion_owner_win_rate)}")
        self.stdout.write(f"  Finalist-owner win rate:      {pct(metrics.finalist_owner_win_rate)}")
        self.stdout.write(f"  Champion-owner top-3 rate:    {pct(metrics.champion_owner_top3_rate)}")
        self.stdout.write(f"  Champion-owner avg rank:      {_number(metrics.champion_owner_avg_rank)}")
        self.stdout.write(f"  Avg winning score:            {metrics.avg_winning_score:.2f}")
        self.stdout.write(f"  Avg second-place score:       {metrics.avg_second_score:.2f}")
        self.stdout.write(f"  Avg 1st-to-2nd gap:           {metrics.avg_first_second_gap:.2f}")
        self.stdout.write(f"  Winner top-team score share:  {pct(metrics.avg_winner_top_team_share)}")
        self.stdout.write("")
        self.stdout.write("Expected standings:")

        manager_rows = sorted(
            result.projections.values(),
            key=lambda projection: (
                projection.average_rank,
                -projection.average_score,
                projection.member.display_name.lower(),
            ),
        )

        for projection in manager_rows[: options["top"]]:
            self.stdout.write(
                f"  {projection.member.display_name:<28} "
                f"avg_score={float(projection.average_score):>6.2f}  "
                f"avg_rank={float(projection.average_rank):>5.2f}  "
                f"win={pct(projection.first_pick_probability):>7}  "
                f"top3={pct(projection.top3_probability):>7}  "
                f"owns champion={pct(projection.champion_owner_probability):>7}"
            )

        self.stdout.write("")
        self.stdout.write("Most common simulated champions:")
        for team_name, count in result.champion_team_counts.most_common(10):
            self.stdout.write(f"  {team_name:<28} {pct(count / result.runs)}")


def _number(value: float) -> str:
    if math.isnan(value):
        return "n/a"
    return f"{value:.2f}"
