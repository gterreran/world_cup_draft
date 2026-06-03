from __future__ import annotations

from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied

from .models import League


def is_platform_owner(user) -> bool:
    """Return True for site-level owners/operators."""
    return bool(
        user
        and user.is_authenticated
        and (user.is_staff or user.is_superuser)
    )


def is_commissioner(user, league: League) -> bool:
    """Return True when the user manages the given league."""
    return bool(
        user
        and user.is_authenticated
        and league.commissioner_id == user.id
    )


def is_participant(user, league: League) -> bool:
    """Return True when the user is linked to a member in the league."""
    if not user or not user.is_authenticated:
        return False

    return league.members.filter(user=user).exists()


def can_manage_league(user, league: League) -> bool:
    """Return True when the user can change league setup/settings."""
    return is_platform_owner(user) or is_commissioner(user, league)


def can_control_draft(user, league: League) -> bool:
    """Return True when the user can control the live draft."""
    return can_manage_league(user, league)


def can_edit_match_results(user) -> bool:
    """Return True when the user can edit official tournament results."""
    return is_platform_owner(user)


def can_view_league(user, league: League) -> bool:
    """Return True when the league's public dashboard can be viewed."""
    return True


def require_league_manager(user, league: League) -> None:
    """Raise PermissionDenied unless the user can manage the league."""
    if not can_manage_league(user, league):
        raise PermissionDenied("Only the commissioner can manage this league.")


def require_draft_controller(user, league: League) -> None:
    """Raise PermissionDenied unless the user can control the draft."""
    if not can_control_draft(user, league):
        raise PermissionDenied("Only the commissioner can control the draft.")


def require_match_result_editor(user) -> None:
    """Raise PermissionDenied unless the user can edit match results."""
    if not can_edit_match_results(user):
        raise PermissionDenied("Only platform owners can edit match results.")
