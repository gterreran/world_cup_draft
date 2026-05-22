from django.db import models

from leagues.models import League, LeagueMember


class StandingEntry(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="standings")
    member = models.ForeignKey(LeagueMember, on_delete=models.CASCADE, related_name="standing_entries")
    points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    wins = models.PositiveSmallIntegerField(default=0)
    draws = models.PositiveSmallIntegerField(default=0)
    losses = models.PositiveSmallIntegerField(default=0)
    teams_advanced = models.PositiveSmallIntegerField(default=0)
    best_finish_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    goal_difference = models.SmallIntegerField(default=0)
    goals_scored = models.PositiveSmallIntegerField(default=0)
    current_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("league", "member")]
        ordering = ["current_rank", "-points", "member__display_name"]

    def __str__(self) -> str:
        return f"{self.member.display_name}: {self.points}"
