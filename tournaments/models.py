from django.db import models
from django.core.exceptions import ValidationError


class Tournament(models.Model):
    class Status(models.TextChoices):
        UPCOMING = "upcoming", "Upcoming"
        ACTIVE = "active", "Active"
        COMPLETE = "complete", "Complete"

    name = models.CharField(max_length=120)
    slug = models.SlugField(unique=True)
    year = models.PositiveIntegerField()
    host = models.CharField(max_length=120, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPCOMING)

    def __str__(self) -> str:
        return f"{self.name} {self.year}"


class NationalTeam(models.Model):
    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="teams")
    name = models.CharField(max_length=120)
    fifa_code = models.CharField(max_length=3)
    confederation = models.CharField(max_length=20, blank=True)
    pot = models.PositiveSmallIntegerField(null=True, blank=True)
    fifa_rank = models.PositiveSmallIntegerField(null=True, blank=True)
    group = models.CharField(max_length=5, blank=True)

    class Meta:
        unique_together = [("tournament", "fifa_code")]
        ordering = ["pot", "name"]

    def __str__(self) -> str:
        return self.name


class TeamTournamentStatus(models.Model):
    class EliminationStage(models.TextChoices):
        GROUP = "group", "Group Stage"
        ROUND_OF_32 = "round_of_32", "Round of 32"
        ROUND_OF_16 = "round_of_16", "Round of 16"
        QUARTERFINAL = "quarterfinal", "Quarterfinal"
        SEMIFINAL = "semifinal", "Semifinal"
        THIRD_PLACE = "third_place", "Third-place Match"
        FINAL = "final", "Final"
        CHAMPION = "champion", "Champion"

    tournament = models.ForeignKey(
        Tournament,
        on_delete=models.CASCADE,
        related_name="team_statuses",
    )
    team = models.OneToOneField(
        NationalTeam,
        on_delete=models.CASCADE,
        related_name="tournament_status",
    )

    advanced_from_group = models.BooleanField(default=False)
    eliminated_stage = models.CharField(
        max_length=30,
        choices=EliminationStage.choices,
        blank=True,
    )
    finish_rank = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["finish_rank", "team__name"]

    def __str__(self) -> str:
        return f"{self.team.name} status"


class Match(models.Model):
    class Stage(models.TextChoices):
        GROUP = "group", "Group Stage"
        ROUND_OF_32 = "round_of_32", "Round of 32"
        ROUND_OF_16 = "round_of_16", "Round of 16"
        QUARTERFINAL = "quarterfinal", "Quarterfinal"
        SEMIFINAL = "semifinal", "Semifinal"
        THIRD_PLACE = "third_place", "Third-place Match"
        FINAL = "final", "Final"

    tournament = models.ForeignKey(Tournament, on_delete=models.CASCADE, related_name="matches")
    stage = models.CharField(max_length=30, choices=Stage.choices)
    kickoff_time = models.DateTimeField(null=True, blank=True)
    home_team = models.ForeignKey(NationalTeam, on_delete=models.PROTECT, related_name="home_matches")
    away_team = models.ForeignKey(NationalTeam, on_delete=models.PROTECT, related_name="away_matches")
    home_score = models.PositiveSmallIntegerField(null=True, blank=True)
    away_score = models.PositiveSmallIntegerField(null=True, blank=True)
    went_to_extra_time = models.BooleanField(default=False)
    went_to_penalties = models.BooleanField(default=False)
    winner = models.ForeignKey(
        NationalTeam,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="matches_won",
    )

    def clean(self):
        super().clean()

        if self.home_team_id == self.away_team_id:
            raise ValidationError("A team cannot play itself.")

        if self.home_score is None or self.away_score is None:
            if self.winner_id is not None:
                raise ValidationError("A winner cannot be set before scores are entered.")
            return

        is_group_stage = self.stage == self.Stage.GROUP
        is_tied = self.home_score == self.away_score

        if is_group_stage:
            if self.went_to_extra_time or self.went_to_penalties:
                raise ValidationError("Group-stage matches cannot go to extra time or penalties.")

            if self.winner_id is not None:
                raise ValidationError("Group-stage matches should not have a winner field set.")

        else:
            if self.winner_id is None:
                raise ValidationError("Knockout matches must have a winner.")

            if self.winner_id not in {self.home_team_id, self.away_team_id}:
                raise ValidationError("Winner must be one of the two teams in the match.")

            if is_tied and not self.went_to_penalties:
                raise ValidationError("A tied knockout match must be decided on penalties.")

            if self.went_to_penalties and not self.went_to_extra_time:
                raise ValidationError("Penalty shootouts should imply extra time.")

            if not is_tied and self.went_to_penalties:
                raise ValidationError("Penalty shootouts should only happen after a tied match.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta:
        ordering = ["kickoff_time", "id"]

    @property
    def is_complete(self) -> bool:
        return self.home_score is not None and self.away_score is not None

    def __str__(self) -> str:
        return f"{self.home_team} vs {self.away_team} ({self.get_stage_display()})"
