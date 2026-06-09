from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any

import redis
from django.conf import settings
from django.utils import timezone

from leagues.models import League
from scoring.models import ProjectionJobState
from scoring.projections import mark_projection_entries_stale

DEFAULT_QUEUE_NAME = "worldcupdraft:projection_jobs"


class ProjectionQueueUnavailable(RuntimeError):
    """Raised when projection work cannot be queued."""


@dataclass(frozen=True)
class ProjectionQueueResult:
    """Summary of a projection queue request."""

    queued: bool
    status: str
    message: str


def projection_queue_name() -> str:
    """Return the Redis queue name used for projection jobs."""

    return getattr(settings, "PROJECTION_JOB_QUEUE", DEFAULT_QUEUE_NAME)


def redis_url() -> str | None:
    """Return the Redis URL configured for background jobs."""

    return getattr(settings, "PROJECTION_REDIS_URL", None) or os.getenv("REDIS_URL")


def get_redis_client() -> redis.Redis:
    """Return a Redis client for background projection jobs."""

    url = redis_url()
    if not url:
        raise ProjectionQueueUnavailable(
            "REDIS_URL is not configured, so projection work cannot be queued."
        )

    return redis.from_url(
        url,
        socket_connect_timeout=5,
        socket_timeout=None,
        decode_responses=True,
        health_check_interval=30,
    )


def request_projection_recompute(
    league: League,
    *,
    reason: str = "Projection recompute requested.",
) -> ProjectionQueueResult:
    """Mark projections stale and queue a background recomputation.

    This is the public API that views and future score-ingestion code should use.
    It intentionally hides the queue backend so Redis can be replaced by another
    task system later without changing callers.
    """

    mark_projection_entries_stale(league, reason=reason)

    state, _ = ProjectionJobState.objects.get_or_create(league=league)

    if state.status == ProjectionJobState.Status.QUEUED:
        state.requested_at = timezone.now()
        state.error_message = ""
        state.save(update_fields=["requested_at", "error_message", "updated_at"])
        return ProjectionQueueResult(
            queued=False,
            status=state.status,
            message="Projection recomputation is already queued.",
        )

    if state.status == ProjectionJobState.Status.RUNNING and not state.is_running_stale():
        state.requested_at = timezone.now()
        state.error_message = ""
        state.save(update_fields=["requested_at", "error_message", "updated_at"])
        return ProjectionQueueResult(
            queued=False,
            status=state.status,
            message="Projection recomputation is already running.",
        )

    job_id = str(uuid.uuid4())
    payload = {
        "job_id": job_id,
        "type": "projection_recompute",
        "league_id": league.id,
        "league_slug": league.slug,
        "reason": reason,
        "requested_at": timezone.now().isoformat(),
    }

    client = get_redis_client()
    client.rpush(projection_queue_name(), json.dumps(payload))

    state.status = ProjectionJobState.Status.QUEUED
    state.last_job_id = job_id
    state.requested_at = timezone.now()
    state.started_at = None
    state.finished_at = None
    state.last_heartbeat_at = None
    state.error_message = ""
    state.save()

    return ProjectionQueueResult(
        queued=True,
        status=state.status,
        message="Projection recomputation queued.",
    )


def decode_projection_job(raw_payload: str | bytes) -> dict[str, Any]:
    """Decode a raw Redis queue payload."""

    if isinstance(raw_payload, bytes):
        raw_payload = raw_payload.decode("utf-8")

    payload = json.loads(raw_payload)

    if payload.get("type") != "projection_recompute":
        raise ValueError(f"Unsupported projection job type: {payload.get('type')!r}")

    if not payload.get("league_id"):
        raise ValueError("Projection job is missing league_id.")

    return payload
