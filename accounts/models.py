from django.conf import settings
from django.db import models


class Profile(models.Model):
    """User-owned app profile and dashboard preferences."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    leagues_followed = models.ManyToManyField(
        "leagues.League",
        related_name="followers",
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self) -> str:
        return f"Profile for {self.user}"
