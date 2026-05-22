from django.db import models

from leagues.models import League, LeagueMember
from tournaments.models import NationalTeam


class TeamAssignment(models.Model):
    league = models.ForeignKey(League, on_delete=models.CASCADE, related_name="team_assignments")
    member = models.ForeignKey(LeagueMember, on_delete=models.CASCADE, related_name="team_assignments")
    national_team = models.ForeignKey(NationalTeam, on_delete=models.CASCADE, related_name="fantasy_assignments")
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("league", "national_team")]
        ordering = ["member__display_name", "national_team__pot", "national_team__name"]

    def __str__(self) -> str:
        return f"{self.member.display_name}: {self.national_team.name}"
