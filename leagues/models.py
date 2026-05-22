from django.conf import settings
from django.db import models

from tournaments.models import Tournament


class League(models.Model):
    class AssignmentMethod(models.TextChoices):
        RANDOM = "random", "Random draw"
        TIERED_RANDOM = "tiered_random", "Tiered random draw"
        MANUAL = "manual", "Commissioner assignment"
        SNAKE = "snake", "Snake draft"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    commissioner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="commissioned_leagues")
    tournament = models.ForeignKey(Tournament, on_delete=models.PROTECT, related_name="leagues")
    teams_per_manager = models.PositiveSmallIntegerField(default=4)
    use_tiers = models.BooleanField(default=True)
    assignment_method = models.CharField(max_length=30, choices=AssignmentMethod.choices, default=AssignmentMethod.TIERED_RANDOM)
    scoring_config = models.JSONField(default=dict, blank=True)
    tiebreaker_config = models.JSONField(default=list, blank=True)
    sleeper_league_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.name


class LeagueMember(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    display_name = models.CharField(max_length=120)
    sleeper_user_id = models.CharField(max_length=40, blank=True)
    sleeper_roster_id = models.CharField(max_length=40, blank=True)
    draft_order = models.PositiveSmallIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("league", "display_name")]
        ordering = ["display_name"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.league})"
