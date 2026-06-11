from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

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

class ProjectionEntry(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="projection_entries")
    member = models.ForeignKey(LeagueMember, on_delete=models.CASCADE, related_name="projection_entries")

    current_points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    max_possible_points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    remaining_possible_points = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    best_case_slots = models.JSONField(default=dict, blank=True)

    simulated_average_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    simulated_average_rank = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    simulated_first_pick_probability = models.DecimalField(max_digits=6, decimal_places=4, default=0)
    simulation_runs = models.PositiveIntegerField(default=0)
    simulation_mode = models.CharField(max_length=20, blank=True)
    simulated_at = models.DateTimeField(null=True, blank=True)

    is_stale = models.BooleanField(default=True)
    stale_reason = models.CharField(max_length=160, blank=True)
    computed_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [("league", "member")]
        ordering = ["member__display_name"]

    def __str__(self) -> str:
        status = "stale" if self.is_stale else "fresh"
        return f"{self.member.display_name}: max {self.max_possible_points} ({status})"



class ProjectionJobState(models.Model):
    """Track background projection recomputation status for one league."""

    class Status(models.TextChoices):
        IDLE = "idle", "Idle"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    INTERRUPTED_DISPLAY_STATUS = "interrupted"

    league = models.OneToOneField(
        League,
        on_delete=models.CASCADE,
        related_name="projection_job_state",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IDLE,
    )
    last_job_id = models.CharField(max_length=64, blank=True)
    requested_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["league__slug"]

    @classmethod
    def stale_running_after(cls) -> timedelta:
        """Return how long a running worker may go silent before it is stale."""

        seconds = getattr(settings, "PROJECTION_WORKER_STALE_AFTER_SECONDS", 120)
        return timedelta(seconds=seconds)

    def is_running_stale(self) -> bool:
        """Return True if this state looks like an abandoned running job."""

        if self.status != self.Status.RUNNING:
            return False

        reference_time = self.last_heartbeat_at or self.started_at
        if reference_time is None:
            return True

        return timezone.now() - reference_time > self.stale_running_after()

    @property
    def effective_status(self) -> str:
        """Return display status, treating stale running jobs as interrupted."""

        if self.is_running_stale():
            return self.INTERRUPTED_DISPLAY_STATUS
        return self.status

    @property
    def effective_status_label(self) -> str:
        """Return a human-readable display label for the effective status."""

        if self.effective_status == self.INTERRUPTED_DISPLAY_STATUS:
            return "Interrupted"
        return self.get_status_display()

    def __str__(self) -> str:
        return f"{self.league.slug}: {self.get_status_display()}"


class ProjectionWorkerStatus(models.Model):
    """Track whether a projection worker process is currently reporting alive."""

    DEFAULT_WORKER_NAME = "projection-worker"

    worker_name = models.CharField(
        max_length=80,
        unique=True,
        default=DEFAULT_WORKER_NAME,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["worker_name"]

    @classmethod
    def offline_after(cls) -> timedelta:
        """Return how long a worker may go silent before being offline."""

        seconds = getattr(settings, "PROJECTION_WORKER_OFFLINE_AFTER_SECONDS", 60)
        return timedelta(seconds=seconds)

    @classmethod
    def get_default(cls) -> "ProjectionWorkerStatus":
        """Return the default projection worker status row."""

        status, _ = cls.objects.get_or_create(
            worker_name=cls.DEFAULT_WORKER_NAME,
        )
        return status

    def is_online(self) -> bool:
        """Return True if the worker has reported recently."""

        if self.last_seen_at is None:
            return False
        return timezone.now() - self.last_seen_at <= self.offline_after()

    @property
    def status_label(self) -> str:
        """Return the display label for worker availability."""

        return "Online" if self.is_online() else "Offline"

    @property
    def status_slug(self) -> str:
        """Return a CSS-friendly status value for worker availability."""

        return "online" if self.is_online() else "offline"

    def __str__(self) -> str:
        return f"{self.worker_name}: {self.status_label}"
