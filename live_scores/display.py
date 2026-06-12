from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import LiveMatchState


@dataclass(frozen=True)
class MatchScoreDisplay:
    """Server-rendered score/status data for one match card.

    Final local ``Match`` results always win. If the local match is not final,
    provider-fed ``LiveMatchState`` is used when available.
    """

    has_score: bool
    is_live: bool
    is_final: bool
    home_score: int | None
    away_score: int | None
    status_label: str
    status_class: str
    detail_label: str = ""


def attach_live_score_displays(matches: Iterable) -> list:
    """Attach ``score_display`` to each match and return the matches as a list."""

    match_list = list(matches)
    match_ids = [match.id for match in match_list if getattr(match, "id", None)]

    live_states_by_match_id = {}
    if match_ids:
        live_states_by_match_id = {
            live_state.match_id: live_state
            for live_state in LiveMatchState.objects.filter(match_id__in=match_ids)
        }

    for match in match_list:
        live_state = live_states_by_match_id.get(match.id)
        match.score_display = build_match_score_display(match, live_state)

    return match_list


def build_match_score_display(match, live_state: LiveMatchState | None = None) -> MatchScoreDisplay:
    """Return the display score/status for one match."""

    if match.is_complete:
        return MatchScoreDisplay(
            has_score=match.home_score is not None and match.away_score is not None,
            is_live=False,
            is_final=True,
            home_score=match.home_score,
            away_score=match.away_score,
            status_label=match.get_status_display(),
            status_class=match.status,
            detail_label=_final_detail_label(match),
        )

    if live_state is not None:
        return MatchScoreDisplay(
            has_score=live_state.home_score is not None and live_state.away_score is not None,
            is_live=_is_live_like(live_state),
            is_final=live_state.status == LiveMatchState.Status.FINAL,
            home_score=live_state.home_score,
            away_score=live_state.away_score,
            status_label=_live_status_label(live_state),
            status_class=_live_status_class(live_state),
            detail_label=_live_detail_label(live_state),
        )

    return MatchScoreDisplay(
        has_score=False,
        is_live=False,
        is_final=False,
        home_score=None,
        away_score=None,
        status_label=match.get_status_display(),
        status_class=match.status,
    )


def _is_live_like(live_state: LiveMatchState) -> bool:
    return live_state.status in {
        LiveMatchState.Status.LIVE,
        LiveMatchState.Status.HALFTIME,
        LiveMatchState.Status.EXTRA_TIME,
        LiveMatchState.Status.PENALTIES,
    }


def _live_status_class(live_state: LiveMatchState) -> str:
    if _is_live_like(live_state):
        return "live"
    return live_state.status or "unknown"


def _live_status_label(live_state: LiveMatchState) -> str:
    if live_state.status == LiveMatchState.Status.LIVE:
        if live_state.minute is not None:
            return f"LIVE {live_state.minute}'"
        return "LIVE"

    if live_state.status == LiveMatchState.Status.HALFTIME:
        return "HT"

    if live_state.status == LiveMatchState.Status.EXTRA_TIME:
        if live_state.minute is not None:
            return f"ET {live_state.minute}'"
        return "ET"

    if live_state.status == LiveMatchState.Status.PENALTIES:
        return "PEN"

    if live_state.status == LiveMatchState.Status.FINAL:
        return "Final"

    return live_state.get_status_display()


def _live_detail_label(live_state: LiveMatchState) -> str:
    if live_state.went_to_penalties:
        return "Penalties"
    if live_state.went_to_extra_time:
        return "Extra time"
    if live_state.provider_state_name and live_state.status not in {
        LiveMatchState.Status.LIVE,
        LiveMatchState.Status.FINAL,
    }:
        return live_state.provider_state_name
    return ""


def _final_detail_label(match) -> str:
    if match.went_to_penalties:
        return "Penalties"
    if match.went_to_extra_time:
        return "After extra time"
    return ""
