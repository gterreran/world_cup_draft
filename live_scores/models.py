from __future__ import annotations

from django.db import models

from .providers.base import PROVIDER_API_FOOTBALL


class ProviderFixtureMapping(models.Model):
    """Map an external provider fixture to one local tournament match.

    The local Match table remains the app's source of truth. This mapping keeps
    provider-specific identifiers and payload details outside the core
    tournament model, so we can review/correct provider mappings independently
    and swap providers without changing the tournament schema.
    """

    class Provider(models.TextChoices):
        API_FOOTBALL = PROVIDER_API_FOOTBALL, "API-Football"

    provider = models.CharField(
        max_length=40,
        choices=Provider.choices,
        default=Provider.API_FOOTBALL,
    )
    provider_fixture_id = models.CharField(max_length=80)
    match = models.ForeignKey(
        "tournaments.Match",
        on_delete=models.CASCADE,
        related_name="provider_mappings",
    )

    provider_league_id = models.CharField(max_length=80, blank=True)
    provider_season_id = models.CharField(max_length=80, blank=True)
    provider_home_name = models.CharField(max_length=160, blank=True)
    provider_away_name = models.CharField(max_length=160, blank=True)
    provider_starting_at = models.DateTimeField(null=True, blank=True)
    confidence = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_fixture_id"],
                name="unique_provider_fixture",
            ),
            models.UniqueConstraint(
                fields=["provider", "match"],
                name="unique_provider_match_mapping",
            ),
        ]
        indexes = [
            models.Index(fields=["provider", "provider_fixture_id"]),
            models.Index(fields=["provider_starting_at"]),
        ]
        ordering = ["provider", "provider_starting_at", "provider_fixture_id"]

    def __str__(self) -> str:
        return f"{self.get_provider_display()} fixture {self.provider_fixture_id} → {self.match}"


class LiveMatchState(models.Model):
    """Provider-fed live state for a match.

    This model is intentionally separate from Match.home_score/away_score.
    Match scores remain final/official app state; LiveMatchState can change many
    times during a game without triggering standings/projection recomputation.
    """

    class Provider(models.TextChoices):
        API_FOOTBALL = PROVIDER_API_FOOTBALL, "API-Football"

    class Status(models.TextChoices):
        SCHEDULED = "scheduled", "Scheduled"
        LIVE = "live", "Live"
        HALFTIME = "halftime", "Half-time"
        EXTRA_TIME = "extra_time", "Extra time"
        PENALTIES = "penalties", "Penalties"
        FINAL = "final", "Final"
        POSTPONED = "postponed", "Postponed"
        CANCELLED = "cancelled", "Cancelled"
        DELAYED = "delayed", "Delayed"
        SUSPENDED = "suspended", "Suspended"
        UNKNOWN = "unknown", "Unknown"

    match = models.OneToOneField(
        "tournaments.Match",
        on_delete=models.CASCADE,
        related_name="live_state",
    )
    provider = models.CharField(
        max_length=40,
        choices=Provider.choices,
        default=Provider.API_FOOTBALL,
    )
    provider_fixture_id = models.CharField(max_length=80, blank=True)

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.UNKNOWN,
    )
    provider_state_id = models.PositiveSmallIntegerField(null=True, blank=True)
    provider_state_code = models.CharField(max_length=60, blank=True)
    provider_state_name = models.CharField(max_length=120, blank=True)
    minute = models.PositiveSmallIntegerField(null=True, blank=True)

    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)
    went_to_extra_time = models.BooleanField(default=False)
    went_to_penalties = models.BooleanField(default=False)
    penalty_home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    penalty_away_score = models.PositiveSmallIntegerField(null=True, blank=True)

    last_seen_at = models.DateTimeField(null=True, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["provider", "provider_fixture_id"]),
            models.Index(fields=["status"]),
            models.Index(fields=["last_seen_at"]),
        ]
        ordering = ["match__kickoff_time", "match__match_number", "match_id"]

    @property
    def has_score(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    def __str__(self) -> str:
        score = ""
        if self.has_score:
            score = f" {self.home_score}-{self.away_score}"
        return f"{self.match}{score} ({self.get_status_display()})"
