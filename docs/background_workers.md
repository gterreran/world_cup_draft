# Background Workers

This document describes the lightweight background-worker infrastructure used by the World Cup Draft app.

The first background job type is max-points projection recomputation.

---

# Why Background Workers Exist

Max-points projections can be computationally expensive, especially early in the tournament when many future outcomes remain possible.

The web app should not calculate projections inside normal page requests because doing so can block navigation and make pages slow to load.

Instead, web requests enqueue projection work and return immediately. A separate worker process consumes the queued job and writes the computed projection rows to PostgreSQL.

---

# Architecture

The app uses a deliberately small custom worker rather than Celery.

```text
Django web service
    marks projections stale
    enqueues projection job
    returns response immediately

Redis
    stores queued projection jobs

Projection worker
    consumes Redis jobs
    recomputes projections
    updates ProjectionEntry rows
    updates ProjectionJobState

PostgreSQL
    stores projection cache and job state
```

Redis is the queue backend.

The worker code is owned by the app so the behavior remains easy to understand and change.

The queue implementation is intentionally hidden behind a small service API so that Redis can be replaced by Celery or another task system later if needed.

---

# Public Queue API

Application code should enqueue projection work through:

```python
from scoring.jobs import request_projection_recompute

request_projection_recompute(
    league,
    reason="Match result changed.",
)
```

Views and future live-score ingestion code should not push directly to Redis.

This keeps queue details centralized in:

```text
scoring/jobs.py
```

---

# Worker Command

Run the worker with:

```bash
python manage.py run_projection_worker
```

For local testing, process one job and exit:

```bash
python manage.py run_projection_worker --once
```

The worker listens to the Redis queue configured by:

```text
PROJECTION_JOB_QUEUE
```

Default:

```text
worldcupdraft:projection_jobs
```

---

# Required Environment Variables

The worker needs Redis.

```text
REDIS_URL=redis://...
```

Optional override:

```text
PROJECTION_REDIS_URL=redis://...
```

Optional queue name override:

```text
PROJECTION_JOB_QUEUE=worldcupdraft:projection_jobs
```

If `PROJECTION_REDIS_URL` is not set, the app uses `REDIS_URL`.

---

# Projection Job State

Projection job state is tracked in:

```text
scoring.ProjectionJobState
```

Each league has one job-state row.

Statuses:

```text
Idle
Queued
Running
Succeeded
Failed
```

The league dashboard displays this status so commissioners can see whether projection work is queued, running, finished, or failed.

---

# Current Behavior

The commissioner projection button no longer computes projections synchronously.

It now:

1. marks projection entries stale
2. queues a background recomputation
3. redirects immediately

Editing a match result also queues a projection recomputation after tournament progression and standings are updated.

The existing synchronous management command remains available:

```bash
python manage.py recompute_projections
python manage.py recompute_projections <league_slug>
```

This is useful for emergency repairs, one-off maintenance, and local debugging.

---

# Recovering Stale Jobs

If the worker process is killed while a projection job is running, the job may remain marked as `Running` in the database. This can happen during local testing, Railway restarts, deployments, or any unexpected worker interruption.

Use the recovery command to mark stale running jobs as failed/recoverable:

```bash
python manage.py recover_projection_jobs
```

By default, the command only recovers running jobs whose heartbeat is stale. Jobs with a recent heartbeat are skipped because they are probably still active.

To recover a specific league:

```bash
python manage.py recover_projection_jobs --league <league_slug>
```

For local debugging, you can force-recover all running jobs:

```bash
python manage.py recover_projection_jobs --all-running
```

Use `--all-running` carefully. It is intended for situations where you know the worker was stopped or the running state is no longer trustworthy.

After recovery, projection recomputation can be requested again through the normal queue API or the commissioner recompute button.

---

# Railway Deployment

Production should run the projection worker as a separate Railway service using the same repository.

Suggested start command:

```bash
python manage.py run_projection_worker
```

The worker service needs access to the same environment variables as the web service, especially:

```text
DATABASE_URL
REDIS_URL
SECRET_KEY
DJANGO_ALLOWED_HOSTS
DJANGO_CSRF_TRUSTED_ORIGINS
```

The worker does not serve HTTP traffic.

---

# Future Live Score Integration

Live score ingestion should reuse the same projection queue API.

When a match becomes final, the live-score service can update the match, recompute standings, and call:

```python
request_projection_recompute(league, reason="Match finalized.")
```

Additional gates can be added later, for example:

```text
Do not recompute projections while another match is still live.
```

That rule should be implemented above the queue layer, not inside the worker itself.

---

# Design Summary

The background-worker design is intentionally modest:

```text
Redis queue
Small custom worker
Centralized queue API
Projection job-state tracking
No Celery for now
```

This solves the immediate problem: expensive projection calculations no longer block normal web requests.
