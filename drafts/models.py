from django.db import models

from leagues.models import League


class DraftState(models.Model):
    class Status(models.TextChoices):
        WAITING = "waiting", "Waiting"
        RUNNING = "running", "Running"
        FINISHED = "finished", "Finished"

    class RevealPhase(models.TextChoices):
        MANAGER = "manager", "Manager revealed"
        TEAM = "team", "Team revealed"
        COMPLETE = "complete", "Complete"

    league = models.OneToOneField(
        League,
        on_delete=models.CASCADE,
        related_name="draft_state",
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.WAITING,
    )
    current_pick_index = models.PositiveIntegerField(default=0)
    reveal_phase = models.CharField(
        max_length=20,
        choices=RevealPhase.choices,
        default=RevealPhase.MANAGER,
    )
    autoplay = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["league__name"]

    @property
    def is_waiting(self) -> bool:
        return self.status == self.Status.WAITING

    @property
    def is_running(self) -> bool:
        return self.status == self.Status.RUNNING

    @property
    def is_finished(self) -> bool:
        return self.status == self.Status.FINISHED

    def __str__(self) -> str:
        return f"{self.league.name}: {self.status} ({self.reveal_phase})"
