from __future__ import annotations

from .models import Profile

from django.contrib.auth.models import AbstractBaseUser


def get_or_create_profile(user: AbstractBaseUser) -> Profile:
    """Return the user's profile, creating it for older accounts if needed."""
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile
