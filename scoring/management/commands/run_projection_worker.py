from __future__ import annotations

import time
from django.utils import timezone

from django.core.management.base import BaseCommand
from redis.exceptions import RedisError

from scoring.jobs import get_redis_client, projection_queue_name
from scoring.models import ProjectionWorkerStatus
from scoring.worker import ProjectionWorkerStatusHeartbeat, process_projection_job


class Command(BaseCommand):
    help = "Run a Redis-backed worker that recomputes projection entries."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process at most one queued job and exit.",
        )
        parser.add_argument(
            "--timeout",
            type=int,
            default=30,
            help="Redis BLPOP timeout in seconds. Defaults to 30.",
        )
        parser.add_argument(
            "--sleep-after-error",
            type=float,
            default=2.0,
            help="Seconds to sleep after a job or Redis error. Defaults to 2.",
        )
        parser.add_argument(
            "--worker-name",
            default=ProjectionWorkerStatus.DEFAULT_WORKER_NAME,
            help="Worker status name to heartbeat under. Defaults to projection-worker.",
        )

    def handle(self, *args, **options):
        client = get_redis_client()
        queue_name = projection_queue_name()
        once = options["once"]
        timeout = options["timeout"]
        sleep_after_error = options["sleep_after_error"]
        worker_name = options["worker_name"]

        worker_heartbeat = ProjectionWorkerStatusHeartbeat(worker_name=worker_name)
        worker_heartbeat.start()

        def log(message: str) -> None:
            self.stdout.write(f"[{timezone.now().isoformat()}] {message}")
            self.stdout.flush()

        log(
            f"Listening for projection jobs on Redis queue {queue_name!r} "
            f"as worker {worker_name!r}."
        )

        try:
            while True:
                try:
                    item = client.blpop(queue_name, timeout=timeout)
                except RedisError as exc:
                    self.stderr.write(self.style.ERROR(f"Redis error: {exc}"))
                    if once:
                        raise
                    time.sleep(sleep_after_error)
                    continue

                if item is None:
                    if once:
                        log("No projection jobs found.")
                        return
                    continue

                _, raw_payload = item

                log("Dequeued projection job from Redis.")

                try:
                    process_projection_job(raw_payload, log=log)
                except Exception as exc:  # noqa: BLE001 - keep long-running worker alive.
                    self.stderr.write(self.style.ERROR(f"Projection job failed: {exc}"))
                    if once:
                        raise
                    time.sleep(sleep_after_error)
                    continue

                log(self.style.SUCCESS("Projection job completed."))

                if once:
                    return
        finally:
            worker_heartbeat.stop()
