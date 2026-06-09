from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable

from django.conf import settings
from django.db import close_old_connections
from django.utils import timezone

from leagues.models import League
from scoring.jobs import decode_projection_job
from scoring.models import ProjectionJobState, ProjectionWorkerStatus
from scoring.projections import recompute_projection_entries

logger = logging.getLogger(__name__)


def process_projection_job(
    raw_payload: str | bytes,
    *,
    log: Callable[[str], None] | None = None,
) -> None:
    """Process one queued projection recomputation job.

    The optional ``log`` callback is intentionally tiny and CLI-friendly. It
    lets the management command report useful progress while keeping this module
    independent from Django command classes.
    """

    def emit(message: str) -> None:
        if log is not None:
            log(message)

    payload = decode_projection_job(raw_payload)
    league_id = payload["league_id"]
    job_id = payload.get("job_id", "")

    emit(
        "Received projection job "
        f"job_id={job_id or '<missing>'} league_id={league_id}."
    )

    league = League.objects.get(id=league_id)
    emit(f"Loaded league slug={league.slug!r} id={league.id}.")
    state, _ = ProjectionJobState.objects.get_or_create(league=league)
    now = timezone.now()

    state.status = ProjectionJobState.Status.RUNNING
    state.last_job_id = job_id
    state.started_at = now
    state.finished_at = None
    state.last_heartbeat_at = now
    state.error_message = ""
    state.save()
    emit(
        "Marked projection job as running "
        f"for league={league.slug!r} job_id={job_id or '<missing>'}."
    )

    heartbeat = ProjectionWorkerHeartbeat(
        league_id=league.id,
        job_id=job_id,
    )
    heartbeat.start()
    emit("Started projection job heartbeat.")

    try:
        emit(f"Starting projection recomputation for league={league.slug!r}.")
        recompute_projection_entries(league)
    except Exception as exc:  # noqa: BLE001 - worker must persist failures.
        logger.exception("Projection recomputation failed for league_id=%s", league_id)
        emit(f"Projection recomputation failed for league={league.slug!r}: {exc}")
        heartbeat.stop()
        emit("Stopped projection job heartbeat after failure.")
        state.status = ProjectionJobState.Status.FAILED
        state.finished_at = timezone.now()
        state.last_heartbeat_at = timezone.now()
        state.error_message = _format_error(exc)
        state.save()
        raise

    heartbeat.stop()
    emit("Stopped projection job heartbeat after success.")
    state.status = ProjectionJobState.Status.SUCCEEDED
    state.finished_at = timezone.now()
    state.last_heartbeat_at = timezone.now()
    state.error_message = ""
    state.save()
    emit(f"Projection recomputation succeeded for league={league.slug!r}.")


class ProjectionWorkerStatusHeartbeat:
    """Update global worker availability while the worker command is alive."""

    def __init__(self, *, worker_name: str = ProjectionWorkerStatus.DEFAULT_WORKER_NAME) -> None:
        self.worker_name = worker_name
        self.interval_seconds = getattr(settings, "PROJECTION_WORKER_STATUS_HEARTBEAT_SECONDS", 15)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"projection-worker-status-{worker_name}",
            daemon=True,
        )

    def start(self) -> None:
        """Start the worker availability heartbeat."""

        now = timezone.now()
        ProjectionWorkerStatus.objects.update_or_create(
            worker_name=self.worker_name,
            defaults={
                "started_at": now,
                "last_seen_at": now,
            },
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the worker availability heartbeat."""

        self._stop_event.set()
        self._thread.join(timeout=1)

    def beat(self) -> None:
        """Record one worker availability heartbeat."""

        ProjectionWorkerStatus.objects.update_or_create(
            worker_name=self.worker_name,
            defaults={"last_seen_at": timezone.now()},
        )

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                close_old_connections()
                self.beat()
            except Exception:  # noqa: BLE001 - status heartbeat must not kill worker.
                logger.exception(
                    "Projection worker status heartbeat failed for worker_name=%s",
                    self.worker_name,
                )
            finally:
                close_old_connections()


class ProjectionWorkerHeartbeat:
    """Update job heartbeat while a projection computation is running."""

    def __init__(self, *, league_id: int, job_id: str) -> None:
        self.league_id = league_id
        self.job_id = job_id
        self.interval_seconds = getattr(settings, "PROJECTION_WORKER_HEARTBEAT_SECONDS", 15)
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name=f"projection-heartbeat-{league_id}",
            daemon=True,
        )

    def start(self) -> None:
        """Start the background heartbeat thread."""

        self._thread.start()

    def stop(self) -> None:
        """Stop the background heartbeat thread."""

        self._stop_event.set()
        self._thread.join(timeout=1)

    def _run(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                close_old_connections()
                ProjectionJobState.objects.filter(
                    league_id=self.league_id,
                    last_job_id=self.job_id,
                    status=ProjectionJobState.Status.RUNNING,
                ).update(last_heartbeat_at=timezone.now())
            except Exception:  # noqa: BLE001 - heartbeat must not kill the worker.
                logger.exception(
                    "Projection heartbeat failed for league_id=%s job_id=%s",
                    self.league_id,
                    self.job_id,
                )
            finally:
                close_old_connections()


def _format_error(exc: Exception) -> str:
    """Return a compact error message for storage in the database."""

    message = "".join(traceback.format_exception_only(type(exc), exc)).strip()
    return message[:1000]
