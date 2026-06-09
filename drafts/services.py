from __future__ import annotations

from dataclasses import dataclass

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from django.db import transaction

from assignments.models import TeamAssignment
from leagues.models import League

from .models import DraftState


class DraftStateError(RuntimeError):
    pass


@dataclass(frozen=True)
class DraftPick:
    pick: int
    manager: str
    team: str
    flag: str
    group: str
    pot: int | None


def get_draft_assignments(league: League):
    """Return assignment rows in the presentation order for a league."""
    if league.assignment_method == League.AssignmentMethod.TIERED_RANDOM:
        assignment_ordering = (
            "reveal_order",
            "national_team__pot",
            "member__display_name",
            "national_team__name",
        )
    else:
        assignment_ordering = (
            "reveal_order",
            "member__display_name",
            "national_team__pot",
            "national_team__name",
        )

    return (
        TeamAssignment.objects.filter(league=league)
        .select_related("member", "national_team")
        .order_by(*assignment_ordering)
    )


def get_draft_picks(league: League) -> list[dict]:
    """Return assignment picks in the presentation order for a league."""
    picks = []
    for index, assignment in enumerate(get_draft_assignments(league), start=1):
        team = assignment.national_team
        picks.append(
            {
                "id": assignment.id,
                "pick": index,
                "manager": assignment.member.display_name,
                "team": team.name,
                "flag": team.flag or "🏳️",
                "group": team.group or "",
                "pot": team.pot,
                "revealed": assignment.revealed,
            }
        )

    return picks


def get_or_create_draft_state(league: League) -> DraftState:
    state, _ = DraftState.objects.get_or_create(league=league)
    return state


def serialize_draft_state(league: League) -> dict:
    """Return the current draft state in a JS-friendly shape."""
    picks = get_draft_picks(league)
    state = get_or_create_draft_state(league)

    if not picks:
        return {
            "status": DraftState.Status.WAITING,
            "index": -1,
            "phase": "idle",
            "autoplay": False,
            "total_picks": 0,
            "picks": [],
        }

    if state.status == DraftState.Status.FINISHED:
        index = len(picks) - 1
        phase = "complete"
    elif state.status == DraftState.Status.WAITING:
        index = -1
        phase = "idle"
    else:
        index = min(state.current_pick_index, len(picks) - 1)
        phase = state.reveal_phase

    return {
        "status": state.status,
        "index": index,
        "phase": phase,
        "autoplay": state.autoplay,
        "total_picks": len(picks),
        "updated_at": state.updated_at.isoformat() if state.updated_at else "",
        "picks": picks,
    }


@transaction.atomic
def start_draft(league: League) -> DraftState:
    _ensure_draft_assignments(league)
    _require_picks(league)

    state = get_or_create_draft_state(league)
    state.status = DraftState.Status.RUNNING
    state.current_pick_index = 0
    state.reveal_phase = DraftState.RevealPhase.MANAGER
    state.autoplay = False
    state.save(
        update_fields=[
            "status",
            "current_pick_index",
            "reveal_phase",
            "autoplay",
            "updated_at",
        ]
    )
    broadcast_draft_state(league)
    return state


@transaction.atomic
def advance_draft(league: League) -> DraftState:
    picks = _require_picks(league)
    state = get_or_create_draft_state(league)

    if state.status == DraftState.Status.WAITING:
        return start_draft(league)

    if state.status == DraftState.Status.FINISHED:
        return state

    if state.reveal_phase == DraftState.RevealPhase.MANAGER:
        _reveal_assignment_for_pick(league, state.current_pick_index)
        state.reveal_phase = DraftState.RevealPhase.TEAM
    elif state.current_pick_index + 1 < len(picks):
        state.current_pick_index += 1
        state.reveal_phase = DraftState.RevealPhase.MANAGER
    else:
        state.status = DraftState.Status.FINISHED
        state.reveal_phase = DraftState.RevealPhase.COMPLETE
        state.autoplay = False

    state.save(
        update_fields=[
            "status",
            "current_pick_index",
            "reveal_phase",
            "autoplay",
            "updated_at",
        ]
    )
    broadcast_draft_state(league)
    return state


@transaction.atomic
def reset_draft(league: League) -> DraftState:
    state = get_or_create_draft_state(league)
    state.status = DraftState.Status.WAITING
    state.current_pick_index = 0
    state.reveal_phase = DraftState.RevealPhase.MANAGER
    state.autoplay = False
    state.save(
        update_fields=[
            "status",
            "current_pick_index",
            "reveal_phase",
            "autoplay",
            "updated_at",
        ]
    )
    TeamAssignment.objects.filter(league=league).update(revealed=False, revealed_at=None)
    broadcast_draft_state(league)
    return state


@transaction.atomic
def set_autoplay(league: League, enabled: bool) -> DraftState:
    state = get_or_create_draft_state(league)
    state.autoplay = bool(enabled) and state.status == DraftState.Status.RUNNING
    state.save(update_fields=["autoplay", "updated_at"])
    broadcast_draft_state(league)
    return state


def _ensure_draft_assignments(league: League) -> None:
    """Generate hidden random assignments if the draft starts from an empty league."""
    if TeamAssignment.objects.filter(league=league).exists():
        return

    from assignments.services import (
        assign_teams_randomly,
        request_projection_recompute_when_assignments_complete,
    )
    from scoring.services import recompute_league_standings

    assign_teams_randomly(league)
    recompute_league_standings(league)
    request_projection_recompute_when_assignments_complete(
        league,
        reason="Assignments generated from live draft start.",
    )
    league.lock_assignments(generated=True)


def _reveal_assignment_for_pick(league: League, pick_index: int) -> None:
    assignments = list(get_draft_assignments(league))

    if pick_index < 0 or pick_index >= len(assignments):
        return

    assignment = assignments[pick_index]
    if assignment.revealed:
        return

    from django.utils import timezone

    assignment.revealed = True
    assignment.revealed_at = timezone.now()
    assignment.save(update_fields=["revealed", "revealed_at"])


def _require_picks(league: League) -> list[dict]:
    picks = get_draft_picks(league)

    if not picks:
        raise DraftStateError("Generate assignments before starting the draft.")

    return picks


def broadcast_draft_state(league) -> None:
    channel_layer = get_channel_layer()

    if channel_layer is None:
        return

    async_to_sync(channel_layer.group_send)(
        f"draft_{league.slug}",
        {
            "type": "draft.state_changed",
        },
    )