from django.conf import settings
from django.db import models
from django.utils import timezone

from tournaments.models import Tournament


class League(models.Model):
    class AssignmentMethod(models.TextChoices):
        RANDOM = "random", "Random draw"
        TIERED_RANDOM = "tiered_random", "Tiered random draw"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    commissioner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="commissioned_leagues")
    tournament = models.ForeignKey(Tournament, on_delete=models.PROTECT, related_name="leagues")
    teams_per_manager = models.PositiveSmallIntegerField(default=4)
    assignment_method = models.CharField(max_length=30, choices=AssignmentMethod.choices, default=AssignmentMethod.TIERED_RANDOM)
    scoring_config = models.JSONField(default=dict, blank=True)
    tiebreaker_config = models.JSONField(default=list, blank=True)
    sleeper_league_id = models.CharField(max_length=40, blank=True)
    assignments_locked = models.BooleanField(default=False)
    assignments_generated_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def is_setup_locked(self) -> bool:
        """Return whether manager/assignment setup should be protected."""
        return self.assignments_locked

    def lock_assignments(self, *, generated: bool = False) -> None:
        """Lock league setup after review or assignment generation."""
        self.assignments_locked = True
        update_fields = ["assignments_locked", "updated_at"]

        if generated:
            self.assignments_generated_at = timezone.now()
            update_fields.append("assignments_generated_at")

        self.save(update_fields=update_fields)

    def unlock_assignments(self) -> None:
        """Unlock league setup while preserving existing assignments."""
        self.assignments_locked = False
        self.save(update_fields=["assignments_locked", "updated_at"])

    def __str__(self) -> str:
        return self.name


class LeagueMember(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    display_name = models.CharField(max_length=120)
    sleeper_user_id = models.CharField(max_length=40, blank=True)
    sleeper_roster_id = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("league", "display_name")]
        ordering = ["display_name"]

    def __str__(self) -> str:
        return f"{self.display_name} ({self.league})"
