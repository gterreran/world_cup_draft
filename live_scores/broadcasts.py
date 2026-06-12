from __future__ import annotations

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .display import build_match_score_display
from .models import LiveMatchState


def tournament_score_group_name(tournament_slug: str) -> str:
    """Return the Channels group name for one tournament's live scores."""

    # Keep the prefix short and avoid punctuation other than underscores. Slugs
    # are already URL-safe, but Channels group names are stricter than URLs.
    safe_slug = tournament_slug.replace("-", "_")
    return f"live_scores_{safe_slug}"


def serialize_match_score_update(match, live_state: LiveMatchState | None = None) -> dict:
    """Return a websocket-safe payload for one match score/status update."""

    if live_state is None:
        live_state = getattr(match, "live_state", None)

    score = build_match_score_display(match, live_state)

    winner = None
    if getattr(match, "winner_id", None):
        winner = {
            "id": match.winner_id,
            "name": match.winner.name,
            "flag": getattr(match.winner, "flag", ""),
        }

    return {
        "type": "live_scores.match_changed",
        "match": {
            "id": match.id,
            "match_number": match.match_number,
            "stage": match.stage,
            "is_complete": match.is_complete,
            "winner": winner,
            "score": {
                "has_score": score.has_score,
                "is_live": score.is_live,
                "is_final": score.is_final,
                "home_score": score.home_score,
                "away_score": score.away_score,
                "status_label": score.status_label,
                "status_class": score.status_class,
                "detail_label": score.detail_label,
            },
        },
    }


def broadcast_match_score_update(match, live_state: LiveMatchState | None = None) -> None:
    """Broadcast one match score/status update to tournament score subscribers."""

    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    tournament = getattr(match, "tournament", None)
    tournament_slug = getattr(tournament, "slug", None)
    if not tournament_slug:
        return

    async_to_sync(channel_layer.group_send)(
        tournament_score_group_name(tournament_slug),
        {
            "type": "match_score_changed",
            "payload": serialize_match_score_update(match, live_state),
        },
    )
