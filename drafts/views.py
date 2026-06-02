from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from leagues.models import League

from .services import (
    DraftStateError,
    advance_draft,
    reset_draft,
    serialize_draft_state,
    set_autoplay,
    start_draft,
)


def draft_state(request, slug: str):
    league = get_object_or_404(League, slug=slug)
    return JsonResponse(serialize_draft_state(league))


@login_required
@require_POST
def draft_start(request, slug: str):
    league = get_object_or_404(League, slug=slug)
    _require_commissioner(request, league)

    try:
        start_draft(league)
    except DraftStateError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(serialize_draft_state(league))


@login_required
@require_POST
def draft_advance(request, slug: str):
    league = get_object_or_404(League, slug=slug)
    _require_commissioner(request, league)

    try:
        advance_draft(league)
    except DraftStateError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse(serialize_draft_state(league))


@login_required
@require_POST
def draft_reset(request, slug: str):
    league = get_object_or_404(League, slug=slug)
    _require_commissioner(request, league)

    reset_draft(league)
    return JsonResponse(serialize_draft_state(league))


@login_required
@require_POST
def draft_autoplay(request, slug: str):
    league = get_object_or_404(League, slug=slug)
    _require_commissioner(request, league)

    enabled = request.POST.get("enabled") == "true"
    set_autoplay(league, enabled)
    return JsonResponse(serialize_draft_state(league))


def _require_commissioner(request, league: League) -> None:
    if league.commissioner != request.user:
        raise PermissionDenied("Only the commissioner can control the draft.")
