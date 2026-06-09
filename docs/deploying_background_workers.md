# Deploying Background Workers on Railway

This document explains how to deploy long-running background workers for the World Cup Draft application on Railway.

The projection worker currently uses this pattern. Future workers, such as a live-score polling worker, should follow the same deployment model.

---

## Why Workers Need Their Own Railway Service

The Django web app and the projection worker are two different long-running processes.

The web service runs the website:

```bash
./start.sh
```

or whatever command is configured for the main web deployment.

The projection worker runs:

```bash
python manage.py run_projection_worker
```

These two commands cannot both be run as the single main web process.

A Railway deployment starts one service command. Therefore, a background worker should be deployed as a separate Railway service, even if it uses the same GitHub repository as the web app.

The worker service still uses the same codebase. It builds from the same repo, imports the same Django project, connects to the same database and Redis instance, and runs the same Python environment. The difference is only the start command.

```text
Same GitHub repo
Same Django code
Same database
Same Redis
Different Railway service
Different start command
No public domain needed
```

---

## Services Required

For the current app, the production Railway project should have at least these services:

```text
web
postgres
redis
projection-worker
```

The names do not need to match exactly, but the roles should be clear.

Suggested names:

```text
world-cup-draft-web
world-cup-draft-postgres
world-cup-draft-redis
world-cup-draft-projection-worker
```

---

## Projection Worker Command

The projection worker should use this start command:

```bash
python manage.py run_projection_worker
```

This command starts a long-running process that listens for projection jobs in Redis.

It should stay alive continuously.

Expected startup log:

```text
Listening for projection jobs on Redis queue 'worldcupdraft:projection_jobs' as worker 'projection-worker'.
```

The worker service does not need a public URL.

---

## Required Environment Variables

The worker needs access to the same core environment variables as the web service.

At minimum:

```env
DATABASE_URL=...
REDIS_URL=...
DJANGO_SECRET_KEY=...
DJANGO_SETTINGS_MODULE=config.settings
```

Depending on the current settings, the exact secret-key variable may be:

```env
DJANGO_SECRET_KEY=...
```

or whichever variable `config/settings.py` expects.

The worker also needs any other project variables required for Django startup.

Optional projection-specific variables:

```env
PROJECTION_REDIS_URL=...
PROJECTION_JOB_QUEUE=worldcupdraft:projection_jobs
```

If `PROJECTION_REDIS_URL` is not set, the projection queue code falls back to `REDIS_URL`.

If `PROJECTION_JOB_QUEUE` is not set, the code uses:

```text
worldcupdraft:projection_jobs
```

---

## Redis Configuration

The projection worker uses Redis as a lightweight job queue.

The web app pushes jobs into Redis.

The worker consumes jobs from Redis.

```text
web service
  ↓ enqueue projection job
Redis
  ↓ worker consumes job
projection-worker service
  ↓ recomputes projections
Postgres
```

The Redis service should expose `REDIS_URL` to both the web service and the projection worker service.

On Railway, this can be done by adding the Redis connection variable to each service that needs it.

---

---

## Railway Service Settings

Use different service settings for the web app and for background workers.

### Projection Worker Service

Recommended settings:

```text
Serverless: OFF
Public domain: NO
Deployment overlap: 0 seconds or very low
Deployment draining / teardown: about 30 seconds
```

The projection worker should not use Serverless mode.

Serverless services are designed around request-driven wakeups. The projection worker is not request-driven; it needs to stay alive and listen to Redis. If the worker sleeps, the web app may enqueue projection jobs but nothing will consume them.

The worker also does not need a public domain because it does not receive browser traffic.

A short draining/teardown window is useful because the worker may be in the middle of a job when Railway redeploys it. A 30-second window gives it a chance to stop cleanly before being force-killed.

Suggested variable:

```env
RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30
```

Keep overlap low for the worker. Running two worker deployments at the same time is usually unnecessary. Redis queue consumption should be safe, but overlapping workers make debugging harder and are not needed right now.

### Main Web Service

Recommended settings:

```text
Serverless: OFF, at least during active testing / tournament use
Public domain: YES
Deployment overlap: about 30 seconds
Deployment draining / teardown: about 30 seconds
Healthcheck: recommended
```

The web app can technically use Serverless mode because HTTP traffic can wake it, but keeping it always-on is safer for this app.

Reasons to keep the web app always-on:

```text
Login/signup pages should feel responsive
Commissioner actions should not cold-start
Live draft pages should not be interrupted
Future websocket/live-score behavior will be simpler
```

Suggested variables:

```env
RAILWAY_DEPLOYMENT_OVERLAP_SECONDS=30
RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30
```

Overlap helps Railway keep the old deployment alive briefly while the new one becomes ready.

Draining gives the old deployment a chance to finish active requests before shutdown.

### Healthcheck

The main web service should have a lightweight healthcheck endpoint, for example:

```text
/healthz/
```

This endpoint should return a simple successful response when Django can start and serve requests.

Example Django view:

```python
from django.http import HttpResponse


def healthz(request):
    return HttpResponse("ok", content_type="text/plain")
```

Example URL registration:

```python
from django.urls import path
from .views import healthz

urlpatterns = [
    path("healthz/", healthz, name="healthz"),
]
```

Then configure the Railway web service healthcheck path as:

```text
/healthz/
```

The worker service does not need an HTTP healthcheck unless a future worker is designed to expose one. Worker health is already tracked in the application through `ProjectionWorkerStatus`.

### Summary

```text
Web service:
  Serverless: OFF
  Public domain: YES
  Overlap: 30s
  Draining: 30s
  Healthcheck: /healthz/

Projection worker:
  Serverless: OFF
  Public domain: NO
  Overlap: 0s or very low
  Draining: 30s
  Healthcheck: not needed
```

## Creating the Worker Service in Railway

In the Railway dashboard:

1. Open the existing World Cup Draft project.
2. Add a new service.
3. Choose the same GitHub repository used by the web app.
4. Name the service something like:

```text
projection-worker
```

5. Configure the service start command as:

```bash
python manage.py run_projection_worker
```

6. Add/copy the required environment variables:
   - `DATABASE_URL`
   - `REDIS_URL`
   - `DJANGO_SECRET_KEY`
   - any other Django settings required by the app
7. Do not generate a public domain for the worker.
8. Deploy the service.
9. Open the worker logs and confirm it is listening for jobs.

---

## Important: The Worker Is Not Started from the Web Shell

Do not start the worker from a Railway shell using:

```bash
python manage.py run_projection_worker
```

That can be useful for temporary debugging, but it is not a persistent deployment.

A shell session is temporary. When the session ends, the worker stops.

The production worker must be a Railway service with its own start command.

---

## Migrations

The worker and web service share the same database.

Migrations should be run once for the project, not separately for every service.

Usually, migrations are run from the web service context or via Railway CLI:

```bash
railway run python manage.py migrate
```

After migrations are applied, both the web service and the worker service will see the updated database schema.

---

## Verifying the Worker in Production

After deploying the worker service, check its logs.

Expected idle state:

```text
Listening for projection jobs on Redis queue 'worldcupdraft:projection_jobs' as worker 'projection-worker'.
```

Then trigger a projection recompute from the app.

Typical triggers:

```text
Commissioner clicks recompute projections
Assignments become complete at draft start
A match result is edited through the app
```

Expected worker logs:

```text
Dequeued projection job from Redis.
Received projection job ...
Loaded league ...
Marked projection job as running ...
Starting projection recomputation ...
Projection recomputation succeeded ...
Projection job completed.
```

In the league detail page, the status should move through something like:

```text
Queued → Running → Fresh
```

The worker status should show as online while the worker service is running.

---

## Local Development

For local testing, run three terminals.

Terminal 1: Django web server

```bash
python manage.py runserver
```

Terminal 2: projection worker

```bash
python manage.py run_projection_worker
```

Terminal 3: optional shell trigger

```bash
python manage.py shell
```

Then:

```python
from leagues.models import League
from scoring.jobs import request_projection_recompute

request_projection_recompute(League.objects.first())
```

The worker terminal should immediately show the job being consumed and processed.

---

## Local Redis URL

For local development, use:

```env
REDIS_URL=redis://127.0.0.1:6379/0
```

Verify Redis is running:

```bash
redis-cli ping
```

Expected output:

```text
PONG
```

On macOS with Homebrew, Redis can usually be started with:

```bash
brew services start redis
```

or temporarily with:

```bash
redis-server
```

---

## Recovering Stale Projection Jobs

If a worker dies while a job is running, the database may still show that projection job as running.

The app uses job heartbeats to detect stale running jobs, but it is useful to have a manual recovery command.

Recover stale running jobs:

```bash
python manage.py recover_projection_jobs
```

Recover stale jobs for one league:

```bash
python manage.py recover_projection_jobs --league my-league-slug
```

Force recovery of all running jobs, even if their heartbeat is recent:

```bash
python manage.py recover_projection_jobs --all-running
```

Use `--all-running` carefully. It is mainly for local testing or manual production recovery when you are sure the worker was interrupted.

On Railway, run the same command through the Railway CLI:

```bash
railway run python manage.py recover_projection_jobs
```

---

## Deploying Future Workers

Future background workers should follow the same pattern.

For example, a future live-score worker might use:

```bash
python manage.py run_live_score_worker
```

It would be deployed as another Railway service:

```text
live-score-worker
```

It would use the same repo and most of the same environment variables.

The pattern remains:

```text
One long-running process = one Railway service
```

---

## Troubleshooting

### Worker service starts but does nothing

Check:

```text
Is REDIS_URL configured?
Is DATABASE_URL configured?
Is DJANGO_SECRET_KEY configured?
Is the worker command correct?
Is the web service using the same Redis queue?
```

The worker should log the Redis queue name at startup.

---

### Jobs remain queued forever

Likely causes:

```text
Worker service is not running
Worker is connected to a different Redis instance
Worker start command is wrong
Worker crashed during startup
```

Check the worker logs first.

---

### League detail shows worker offline

Likely causes:

```text
Projection worker service is stopped
Worker crashed
Worker cannot connect to database
Worker cannot update ProjectionWorkerStatus
```

Restart/redeploy the worker service and check logs.

---

### League detail shows job interrupted

This means a job was marked running but its heartbeat became stale.

Run:

```bash
python manage.py recover_projection_jobs
```

Then trigger recomputation again.

---

### Web app works but worker crashes

The worker imports the same Django project as the web service, but it may still be missing environment variables.

Compare the web service variables and worker service variables.

The worker generally needs the same Django/database/Redis settings as the web service.

---

## Summary

The projection worker is deployed as a separate Railway service because it is a separate long-running process.

It uses the same GitHub repository as the web app, but runs a different command:

```bash
python manage.py run_projection_worker
```

The web service remains responsible for serving pages and enqueueing jobs.

The worker service is responsible for consuming projection jobs and updating cached projection results.

This keeps the website responsive and gives the app a reusable background-processing pattern for future features.
