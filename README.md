# World Cup Draft

A production-ready fantasy World Cup platform with live scoring, animated drafts, real-time tournament pages, background projections, and commissioner tools.

World Cup Draft turns the FIFA World Cup into a fantasy draft game: league commissioners create leagues, assign national teams to managers, reveal picks through a live draft experience, and follow scoring as the real tournament unfolds.

The project is built as a full-stack Django application with PostgreSQL, Redis, Django Channels, background workers, provider-based live score ingestion, and a deployed Railway production architecture.

---

## Why this project is interesting

This is not a toy bracket app. It is a small production system with several real-world engineering concerns:

- **Live external data ingestion** from API-Football.
- **Provider-to-local fixture mapping** with safety checks and alias normalization.
- **Real-time score updates** through WebSockets.
- **Recoverable background workers** for live scores and projection jobs.
- **Cached max-points projections** to keep request/response pages fast.
- **Stateful public live draft rooms** with commissioner controls.
- **Public tournament pages** plus authenticated commissioner workflows.
- **Production deployment** on Railway with separate web, Redis, PostgreSQL, projection worker, and live-score worker services.

The app is designed around one core principle:

> PostgreSQL is the source of truth. WebSockets and workers are delivery mechanisms, not state owners.

That makes the system resilient to page refreshes, late joins, worker restarts, process crashes, and provider-feed interruptions.

---

## Core features

### Fantasy leagues

- Create and manage fantasy World Cup leagues.
- Import league members from Sleeper.
- Configure scoring and tiebreakers.
- Public league detail pages for standings and revealed assignments.
- Registered users can follow leagues and maintain a personalized dashboard.
- Commissioners have protected management tools.

See: [`docs/roles_and_capabilities.md`](docs/roles_and_capabilities.md)

### Team assignments and reveal workflow

- Random assignment of national teams to fantasy managers.
- Assignment constraints, including avoiding multiple teams from the same World Cup group for one manager.
- Manual commissioner assignment controls.
- Lock/unlock workflow to prevent accidental edits.
- Hidden/revealed assignment state so commissioners can prepare assignments before public reveal.
- Assignment reveal controls for draft-style presentations.

See: [`docs/teams_assignments.md`](docs/teams_assignments.md)

### Live draft room

The app includes a shared live draft experience where a commissioner controls the reveal and viewers follow along without refreshing.

Architecture highlights:

- Persistent `DraftState` stored in PostgreSQL.
- Django Channels WebSocket notifications.
- Redis channel layer in production.
- Public viewer page and commissioner controls.
- Viewer presence tracking.
- Reconnect-safe state model.

See: [`docs/live_draft.md`](docs/live_draft.md)

### Tournament pages

Public tournament pages include:

- Full tournament schedule.
- Group stage standings.
- Knockout bracket.
- User-local kickoff time rendering in the browser.
- Live and final score display.
- WebSocket score updates without page refresh.

### Live score ingestion

Live scores are ingested by a dedicated worker service.

The live-score architecture separates transient provider data from canonical tournament state:

```text
API-Football
    ↓
ProviderFixtureMapping
    ↓
LiveMatchState
    ↓
canonical Match finalization
    ↓
standings, scoring, projections
    ↓
WebSocket broadcast
```

Important design choices:

- API-Football is treated as an upstream feed, not the runtime data model.
- `Match` remains the local source of truth.
- `LiveMatchState` stores transient live scores and provider status.
- Provider fixture IDs are mapped through `ProviderFixtureMapping`, keeping the core tournament model provider-neutral.
- Final scores are committed only when the provider reports final-like statuses.
- Startup recovery checks past mapped fixtures and applies finals missed while the worker was offline.
- The worker uses a fast polling cadence around live games and a slower idle cadence otherwise.

See: [`docs/live_scores.md`](docs/live_scores.md)

### Max-points projections

The app computes cached “maximum possible points” projections for each fantasy manager.

This is intentionally not recomputed during page rendering. Instead:

```text
match/assignment/scoring change
    ↓
projection entries marked stale
    ↓
projection job queued in Redis
    ↓
projection worker recomputes
    ↓
cached ProjectionEntry rows updated
    ↓
league page reads cached results
```

The projection engine avoids brute-force tournament enumeration by compressing future possibilities into compact team options:

- eliminated
- first in group
- second in group
- qualified third-place bracket node

It also accounts for position-compatible group points, FIFA third-place allocation rules, and bracket-node compatibility.

See: [`docs/projections.md`](docs/projections.md)

---

## Architecture

```text
Browser
  ├── server-rendered Django pages
  └── WebSocket clients
          ↓
Django web service
  ├── league/tournament views
  ├── commissioner workflows
  ├── draft controls
  └── WebSocket consumers
          ↓
PostgreSQL
  ├── leagues, members, assignments
  ├── tournament matches and standings
  ├── live score snapshots
  ├── projection cache
  └── draft state
          ↑
Redis
  ├── projection job queue
  └── Channels/WebSocket layer
          ↑
Background workers
  ├── projection worker
  └── live-score worker
          ↑
API-Football
```

Production services:

```text
web
PostgreSQL
Redis
projection-worker
live-score-worker
```

See:

- [`docs/background_workers.md`](docs/background_workers.md)
- [`docs/deploying_background_workers.md`](docs/deploying_background_workers.md)
- [`docs/deployment.md`](docs/deployment.md)

---

## Tech stack

- **Backend:** Django, Python
- **Database:** PostgreSQL
- **Async / realtime:** Django Channels, WebSockets, Redis
- **Background work:** custom Redis-backed worker pattern
- **Frontend:** server-rendered Django templates, vanilla JavaScript
- **Live data:** API-Football
- **Deployment:** Railway
- **Static files:** WhiteNoise
- **Auth:** Django auth with custom profile/following behavior

---

## Local development

Install dependencies, configure environment variables, and run migrations:

```bash
python manage.py migrate
python manage.py runserver
```

Run the projection worker:

```bash
python manage.py run_projection_worker
```

Run the live-score worker:

```bash
python manage.py run_live_score_worker fifa-world-cup-2026
```

For one-off live-score testing:

```bash
python manage.py run_live_score_worker fifa-world-cup-2026 --once --force-poll --verbosity 2
```

For local WebSocket testing with Redis:

```env
USE_REDIS_CHANNEL_LAYER=True
REDIS_URL=redis://127.0.0.1:6379/0
```

Then start Redis and run the Django development server.

---

## Environment variables

Core production variables:

```env
SECRET_KEY=...
DJANGO_DEBUG=False
DATABASE_URL=...
REDIS_URL=...
USE_REDIS_CHANNEL_LAYER=True
```

Live-score worker variables:

```env
LIVE_SCORES_PROVIDER=api_football
API_FOOTBALL_API_KEY=...
API_FOOTBALL_WORLD_CUP_LEAGUE_ID=1
API_FOOTBALL_WORLD_CUP_SEASON=2026
LIVE_SCORES_POLL_INTERVAL_SECONDS=15
LIVE_SCORES_IDLE_SLEEP_SECONDS=300
LIVE_SCORES_KICKOFF_BUFFER_MINUTES=15
```

Projection worker variables:

```env
PROJECTION_REDIS_URL=...
PROJECTION_JOB_QUEUE=worldcupdraft:projection_jobs
```

See: [`docs/deployment.md`](docs/deployment.md)

---

## Operational behavior

The app is designed to recover from common production issues:

- If a user refreshes during a live draft, the page reloads current state from PostgreSQL.
- If a user opens a tournament page mid-match, the current live score is read from `LiveMatchState`.
- If the live-score worker restarts during a match, it immediately checks for live fixtures.
- If the live-score worker was offline while games finished, startup recovery checks past fixtures and applies missing final results.
- If projections are stale, league pages can show cached state while the worker recomputes asynchronously.
- If WebSocket messages are missed, refreshing the page recovers from database state.

---

## What I wanted to demonstrate

This project was built to explore the engineering behind a real-time sports application, not just the UI around a bracket.

It demonstrates:

- system decomposition across web services and workers
- external API ingestion and normalization
- provider-neutral data modeling
- asynchronous job processing without overengineering with Celery
- WebSocket updates with database-backed recoverability
- production deployment with multiple cooperating services
- careful separation between transient live data and canonical app state
- algorithmic optimization for projection calculations
- permission modeling for public, registered, commissioner, and admin users

The result is a deployed, real-time fantasy tournament platform that can be followed publicly while the tournament is happening.

---

## Documentation

Detailed technical notes live in [`docs/`](docs/):

- [`docs/live_scores.md`](docs/live_scores.md)
- [`docs/projections.md`](docs/projections.md)
- [`docs/background_workers.md`](docs/background_workers.md)
- [`docs/deploying_background_workers.md`](docs/deploying_background_workers.md)
- [`docs/deployment.md`](docs/deployment.md)
- [`docs/live_draft.md`](docs/live_draft.md)
- [`docs/roles_and_capabilities.md`](docs/roles_and_capabilities.md)
- [`docs/teams_assignments.md`](docs/teams_assignments.md)

---

## Status

The app has reached a functional 1.0 milestone:

- league creation and management
- team assignment workflows
- live draft experience
- public tournament pages
- live score ingestion
- WebSocket score updates
- background projection worker
- production deployment

Future improvements may include richer live standings updates, more detailed match event feeds, automated provider schedule synchronization, and expanded commissioner analytics.
