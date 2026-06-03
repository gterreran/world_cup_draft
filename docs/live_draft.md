# Live Draft Feature

This document summarizes the development of the live draft feature for the World Cup Draft app.

## Goal

The goal was to turn the existing draft room presentation into a live shared event.

The commissioner should be able to control the draft from one page, while viewers with the live link should be able to follow the reveal in real time without refreshing.

## Final Architecture

The live draft uses:

* PostgreSQL as the source of truth
* Django views for commissioner actions
* Django Channels for WebSocket connections
* Redis as the production channel layer
* JavaScript on the client to render incoming state changes

The key design decision is that WebSockets are not the source of truth. They are only the notification mechanism.

The flow is:

```text
Commissioner action
    ↓
POST endpoint
    ↓
DraftState updated in PostgreSQL
    ↓
WebSocket event broadcast
    ↓
Viewer fetches current state
    ↓
Viewer UI updates
```

This means the draft remains recoverable if a viewer refreshes, joins late, disconnects, or if the server restarts.

## Persistent Draft State

A new `drafts` app was introduced to isolate live draft behavior from league and assignment logic.

The core model stores the current state of the draft:

* league
* current pick index
* reveal phase
* draft status
* autoplay state
* updated timestamp

The assigned teams themselves are not duplicated in the draft state. They remain stored in the existing assignment models. The draft state only tracks where the reveal presentation currently is.

## Commissioner and Viewer Pages

The original draft room page was split conceptually into two roles:

```text
Commissioner page
    can start, advance, autoplay, and control the draft

Public live page
    can view the draft but cannot control it
```

The public live page can be shared with viewers. Viewers do not need to refresh the page during the draft.

## WebSocket Design

The WebSocket consumer subscribes each browser connection to a league-specific room:

```text
draft_<league-slug>
```

When a draft action changes state, the server broadcasts:

```json
{
  "type": "draft.state_changed"
}
```

The browser receives this event and then fetches the authoritative state from the JSON endpoint.

This was chosen instead of sending the full state through the WebSocket because it avoids duplicated serialization logic and keeps PostgreSQL as the only source of truth.

## Viewer Presence

The live draft page also tracks connected viewers.

When a socket connects, it is added to the room presence set. When it disconnects, it is removed. The commissioner page receives a viewer count update.

This is useful during a live draft because the commissioner can see whether people have joined the room before starting.

## Socket Lifecycle

The WebSocket stays open while the draft is waiting or running.

When the draft reaches the complete state:

* the page renders the final state
* autoplay stops
* reconnect timers are cleared
* the WebSocket closes
* completed draft pages do not open a new socket on refresh

This avoids keeping unnecessary idle sockets alive after the draft is over.

## Local Development

Local development initially used Redis, but Redis timeout issues appeared with the installed Redis Python client.

For local development, the channel layer can use:

```python
channels.layers.InMemoryChannelLayer
```

This works well for one local Django process.

## Railway Deployment

Production WebSockets require Redis because Railway may run the app in a separate deployed process and the channel layer must be shared outside process memory.

Railway uses:

```text
USE_REDIS_CHANNEL_LAYER=True
REDIS_URL=${{Redis.REDIS_URL}}
```

The Django service should continue using PostgreSQL for persistent state:

```text
DATABASE_URL=${{Postgres.DATABASE_URL}}
```

## Redis Issue Encountered

During Railway testing, WebSockets connected successfully but Redis timed out after a few seconds.

Symptoms:

* viewer page connected
* live updates briefly worked
* viewer count kept increasing unexpectedly
* Railway logs showed:

```text
Timeout reading from redis.railway.internal:6379
```

The viewer count was valuable because it revealed repeated reconnects.

The issue was resolved by explicitly pinning the Redis Python client dependency:

```text
channels-redis==4.2.1
redis==5.0.8
```

## Important Lessons

### WebSockets should not own application state

The WebSocket layer should notify clients that something changed. PostgreSQL should remain authoritative.

### Live pages should support late joins

A viewer who joins halfway through the draft should immediately see the current state.

### Presence counts are useful operational signals

The viewer count helped detect reconnect loops caused by Redis timeouts.

### Production and local channel layers can differ

The in-memory channel layer is convenient locally. Redis is required for production.

## Future Improvements

Possible future improvements include:

* better commissioner/viewer role separation
* public/private league permissions
* QR code for the public draft link
* fullscreen draft mode
* sound effects
* countdown before each reveal
* improved reconnect UI
* Redis-backed presence with TTLs
* dedicated draft control page separate from presentation view
