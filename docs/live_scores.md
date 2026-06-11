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

The normalized fixture shape hides provider payload details from the rest of the app.

## Next slices

1. Add the polling worker: `python manage.py run_live_score_worker`.
2. Update `LiveMatchState` from mapped provider fixtures.
3. Add a shared final-result service used by both manual match edits and provider final ingestion.
4. Add WebSocket broadcasts so visible pages update without reload.
