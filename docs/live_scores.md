# Live Scores Integration

This feature integrates an external live-score provider while keeping the app's local `Match` rows as the source of truth.

The current default provider is **API-Football / API-SPORTS**. The app-level code is intentionally provider-neutral so we can swap providers later without changing the tournament/scoring model.

## Design

The provider is treated as an upstream data feed, not as the runtime tournament model.

```text
provider fixtures/livescores
↓
ProviderFixtureMapping
↓
local Match
↓
LiveMatchState during play
↓
final Match result after provider final state
↓
existing scoring/projection pipeline
```

The important separation is:

- `Match.home_score` / `Match.away_score`: final official app result only.
- `LiveMatchState.home_score` / `LiveMatchState.away_score`: transient provider-fed live score.
- `ProviderFixtureMapping`: external fixture IDs mapped to local matches.

This avoids recomputing standings/projections on every live polling tick.

## Environment variables

```bash
LIVE_SCORES_PROVIDER=api_football
API_FOOTBALL_API_KEY=...
API_FOOTBALL_BASE_URL=https://v3.football.api-sports.io
API_FOOTBALL_WORLD_CUP_LEAGUE_ID=1
API_FOOTBALL_WORLD_CUP_SEASON=2026
API_FOOTBALL_TIMEOUT_SECONDS=15
API_FOOTBALL_LIVE_STATUS_CODES=1H-HT-2H-ET-BT-P-LIVE
LIVE_SCORES_POLL_INTERVAL_SECONDS=15
LIVE_SCORES_IDLE_SLEEP_SECONDS=300
LIVE_SCORES_KICKOFF_BUFFER_MINUTES=15
```

`API_SPORTS_API_KEY` is also accepted as an alias for `API_FOOTBALL_API_KEY`.

## Dry-run inspection commands

Inspect live-score payloads without touching the database:

```bash
python manage.py inspect_provider_live
python manage.py inspect_provider_live --raw
python manage.py inspect_provider_live --status-codes 1H-HT-2H-ET-BT-P-LIVE
```

Inspect fixture payloads by date or range:

```bash
python manage.py inspect_provider_fixtures --date 2026-06-11
python manage.py inspect_provider_fixtures --start-date 2026-06-11 --end-date 2026-07-19
```

Print raw JSON while learning the provider payload shape:

```bash
python manage.py inspect_provider_fixtures --date 2026-06-11 --raw
```

## Fixture mapping

Dry-run mapping against local `Match` rows:

```bash
python manage.py map_provider_fixtures world-cup-2026
```

Commit only mappings above the confidence threshold:

```bash
python manage.py map_provider_fixtures world-cup-2026 --commit
```

Tune matching if needed:

```bash
python manage.py map_provider_fixtures world-cup-2026 \
  --kickoff-tolerance-minutes 240 \
  --threshold 85 \
  --commit
```

## API-Football notes

The default client calls the API-Football `/fixtures` endpoint with the configured World Cup league and season:

```text
league=1
season=2026
```

For live polling, it uses the configured status filter:

```text
status=1H-HT-2H-ET-BT-P-LIVE
```

For direct fixture-detail checks, the worker uses provider fixture ids through the normal fixtures endpoint. This is important because final-like statuses such as `FT`, `AET`, or `PEN` may no longer appear in the live-only status filter after a match ends.

The normalized fixture shape hides provider payload details from the rest of the app.

## Live-score worker

After fixture mappings have been committed, run one safe polling pass:

```bash
python manage.py run_live_score_worker fifa-world-cup-2026 --once --force-poll
```

`--force-poll` is useful for smoke tests because it calls the provider live-fixtures endpoint even when no local match is close to kickoff.

For the long-running worker service:

```bash
python manage.py run_live_score_worker fifa-world-cup-2026
```

The worker no longer uses a fixed upper active-window threshold after kickoff. Instead it uses two cadences:

```text
Fast cadence:
  sleep LIVE_SCORES_POLL_INTERVAL_SECONDS

Idle cadence:
  sleep LIVE_SCORES_IDLE_SLEEP_SECONDS
```

The fast cadence is used when either condition is true:

```text
next mapped kickoff is within LIVE_SCORES_KICKOFF_BUFFER_MINUTES
OR
at least one provider fixture is currently tracked as live
```

The worker forces an immediate live-fixtures check on startup. This is a safety measure for deploys/restarts that happen after kickoff while a match is already in progress.

During fast cadence, the worker:

```text
polls provider live fixtures
updates LiveMatchState for mapped fixtures
tracks whether any returned mapped fixtures are live-like
```

If the live feed returns no fixtures while the worker was tracking live fixtures, it confirms those tracked fixture ids through direct fixture-detail lookup before deciding that no games are live anymore.

During idle cadence, the worker performs a lower-frequency direct fixture-detail check for mapped matches whose local kickoff time has already passed and whose local `Match.status` is not terminal. This catches final-like provider statuses even if a finished match has disappeared from the live-only endpoint.

The first worker slices are intentionally conservative. They update `LiveMatchState` for provider fixtures that already have a `ProviderFixtureMapping`. They do **not** update `Match.home_score`, `Match.away_score`, `Match.status`, standings, projections, or websockets yet.

Useful options:

```bash
python manage.py run_live_score_worker fifa-world-cup-2026 --once
python manage.py run_live_score_worker fifa-world-cup-2026 --once --force-poll
python manage.py run_live_score_worker fifa-world-cup-2026 --poll-interval 15 --idle-sleep 300
python manage.py run_live_score_worker fifa-world-cup-2026 --kickoff-buffer-minutes 15
python manage.py run_live_score_worker fifa-world-cup-2026 --fixture-detail-batch-size 20
```

## Next slices

1. Add a shared final-result service used by both manual match edits and provider final ingestion.
2. Commit provider final scores into local `Match` rows through that shared service.
3. Trigger standings/projection refresh only when a match becomes final.
4. Add WebSocket broadcasts so visible pages update without reload.

## Mapping safety checks

`map_provider_fixtures` intentionally maps by kickoff time + team names, not by provider fixture id or provider match number.

The mapper normalizes common provider/local naming differences before scoring, including examples such as:

```text
South Korea → Korea Republic
Czech Republic → Czechia
USA → United States
Ivory Coast → Côte d'Ivoire
Cape Verde Islands → Cape Verde
Türkiye/Turkey → Türkiye
```

If the provider payload exposes an explicit tournament match number, the command compares it with the local `Match.match_number` and prints one of these notes:

```text
provider_match_number=21 OK
MATCH NUMBER MISMATCH provider=21 local=22
```

A match-number mismatch is diagnostic feedback only. It is not used as the primary mapping key because provider match-number fields are not guaranteed to exist or remain stable across providers. If no explicit match-number field is present in the normalized provider payload, the command prints a summary warning and continues using kickoff time + team names.

## Final-result ingestion

The live-score worker now has two layers:

1. Live polling updates `LiveMatchState` for mapped provider fixtures.
2. Direct fixture-detail checks confirm final statuses after a fixture disappears from the live-only endpoint.

When a mapped provider fixture is explicitly final, the worker can commit the result into the local `Match` row through the shared tournament service:

```text
provider final fixture
↓
LiveMatchState updated
↓
apply_final_match_result(...)
↓
Match.status = final
↓
tournament progression/team statuses recomputed
↓
all league standings refreshed
↓
projection recompute jobs queued
```

The command applies final results by default:

```bash
python manage.py run_live_score_worker fifa-world-cup-2026
```

For diagnostics, keep the worker in live-state-only mode:

```bash
python manage.py run_live_score_worker fifa-world-cup-2026 --no-apply-final-results
```

Manual match edits use the same `apply_final_match_result(...)` service, so provider-final ingestion and staff-entered scores share one scoring/projection path.

## WebSocket score updates

The server-rendered score UI can also receive live score/status changes over a tournament-scoped WebSocket:

```text
/ws/tournaments/<tournament-slug>/scores/
```

Pages that display match scores include `static/js/live_scores.js`. The script subscribes to the tournament score stream and updates any visible match card with matching `data-live-score-match-id` attributes.

The live-score worker broadcasts when:

```text
LiveMatchState is created or display-relevant fields change
A provider final result is committed to the local Match row
```

In local development, cross-process broadcasts require Redis because the worker and the web server are separate processes. Use:

```bash
USE_REDIS_CHANNEL_LAYER=True
REDIS_URL=redis://127.0.0.1:6379/0
```

Without Redis, the pages still work after manual refresh, but worker-originated WebSocket broadcasts will not cross from the worker process to the web process.
