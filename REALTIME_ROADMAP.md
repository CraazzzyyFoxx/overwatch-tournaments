# Realtime Architecture Roadmap

## Approach

Build a shared workspace-level realtime platform instead of a balancer-only channel. The balancer becomes the first consumer of this platform, and the same foundation can later support registrations, check-in, activity feed, notifications, and presence.

Use `parser-service` as the first realtime gateway because it already contains working WebSocket patterns and WebSocket auth helpers. Keep balancer business logic in `balancer-service` and heavy async execution in `balancer-worker`.

## Scope

- In:
- Shared realtime updates at workspace scope
- Persistent event log in Postgres
- Shared live visibility for balancer runs, progress, variants, save, and export
- Snapshot, replay, and reconnect support
- Compatibility path from the current `SSE + Redis job_store` flow

- Out:
- Collaborative drag-and-drop editing in the first iteration
- Presence, cursors, and rich collaboration signals
- A brand new dedicated infrastructure service in phase one
- Removal of Rabbit or Redis in the initial rollout

## Target Architecture

- `Command API`
  Receives user actions such as run balance, save result, export result, approve registration, and so on.
- `Domain Services`
  Change state and emit domain events.
- `Persistent Event Log`
  Stores realtime events in Postgres.
- `Pub/Sub Fan-out`
  Delivers live events quickly to the gateway.
- `Workspace WebSocket Gateway`
  Authenticates users, serves snapshot and replay, and broadcasts live events.
- `Frontend Realtime Store`
  Reconstructs state from snapshot plus events instead of per-page local subscriptions.

## Repository Placement

### Realtime gateway

- Service: `parser-service`
- Reason:
- It already has WebSocket routes in [backend/parser-service/src/routes/captain.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/routes/captain.py)
- It already has WebSocket auth helpers in [backend/parser-service/src/core/auth.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/core/auth.py)
- Frontend already knows how to build parser WebSocket URLs in [frontend/src/services/captain.service.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/services/captain.service.ts)

### Balancer commands and domain logic

- Service: `balancer-service`
- Reason:
- It already owns balancer routes, save/export logic, and admin operations

### Async execution

- Service: `balancer-worker`
- Reason:
- It already owns background execution and should remain the producer of progress and result events

### Source of truth

- Storage: `Postgres`
- Reason:
- Redis should remain a transport or acceleration layer, not the authoritative store

## Phase 1: Data Model

Add persistent entities for run lifecycle and a shared workspace event log.

### 1. `balancer.balance_run`

Purpose: one execution of a balancing algorithm.

Suggested fields:

- `id`
- `workspace_id`
- `tournament_id`
- `requested_by`
- `status`
- `algorithm`
- `config_json`
- `input_snapshot_json`
- `active_variant_id`
- `started_at`
- `finished_at`
- `error_text`
- `current_stage`
- `current_progress_json`

Suggested indexes:

- `(workspace_id, created_at desc)`
- `(tournament_id, created_at desc)`
- partial unique index for one active run per tournament where status is `queued` or `running`

### 2. `balancer.balance_run_variant`

Purpose: intermediate and final variants generated during a run.

Suggested fields:

- `id`
- `run_id`
- `workspace_id`
- `tournament_id`
- `variant_number`
- `is_final`
- `is_selected`
- `objective_score`
- `statistics_json`
- `result_json`
- `created_at`

Suggested indexes:

- `(run_id, variant_number)`
- `(tournament_id, created_at desc)`

### 3. `realtime.workspace_event`

Purpose: shared event log for all realtime domains.

Suggested fields:

- `id`
- `workspace_id`
- `tournament_id`
- `domain`
- `event_type`
- `entity_type`
- `entity_id`
- `actor_user_id`
- `schema_version`
- `payload_json`
- `created_at`

Suggested indexes:

- `(workspace_id, id)`
- `(workspace_id, domain, id)`
- `(workspace_id, tournament_id, id)`

### Files

- Update [backend/shared/models/balancer.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/models/balancer.py)
- Add [backend/shared/models/realtime.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/models/realtime.py)
- Add a migration in `backend/migrations/versions/`

## Phase 2: Event Contract

Define a single versioned event envelope from day one.

### New shared schemas

- Add [backend/shared/schemas/realtime.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/schemas/realtime.py)

Core models:

- `WorkspaceEventEnvelope`
- `WorkspaceSnapshotEnvelope`
- `BalanceRunCreatedPayload`
- `BalanceRunProgressPayload`
- `BalanceRunVariantPayload`
- `BalanceRunCompletedPayload`
- `BalanceResultSavedPayload`
- `BalanceResultExportedPayload`

Example envelope:

```python
class WorkspaceEventEnvelope(BaseModel):
    event_id: int
    workspace_id: int
    tournament_id: int | None = None
    domain: str
    event_type: str
    entity_type: str | None = None
    entity_id: int | str | None = None
    actor_user_id: int | None = None
    schema_version: int = 1
    occurred_at: datetime
    payload: dict[str, Any]
```

### Initial balancer event types

- `balance.run.created`
- `balance.run.started`
- `balance.run.progress`
- `balance.run.variant.generated`
- `balance.run.completed`
- `balance.run.failed`
- `balance.run.cancelled`
- `balance.result.selected`
- `balance.result.saved`
- `balance.result.exported`

## Phase 3: Event Publisher Layer

Create a shared publisher that both persists events and emits them to live transport.

### New modules

- Add [backend/shared/services/realtime_store.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/services/realtime_store.py)
- Add [backend/shared/services/realtime_publisher.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/services/realtime_publisher.py)

`realtime_store` responsibilities:

- `append_workspace_event(session, ...)`
- `list_workspace_events_since(session, workspace_id, after_id, ...)`
- `build_workspace_snapshot(session, workspace_id, domain="balancer", tournament_id=None)`

`realtime_publisher` responsibilities:

- `publish_workspace_event(session, broker, envelope)`
- persist first
- publish second

### Transport choice for first iteration

Use Redis pub/sub as the initial fan-out transport because Redis already exists in the stack. Keep Postgres as the source of truth.

## Phase 4: Balance Run Service Layer

The current lifecycle is spread across:

- [backend/balancer-service/src/views.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/views.py)
- [backend/balancer-service/serve.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/serve.py)
- [backend/balancer-service/src/core/job_store.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/core/job_store.py)

Move that lifecycle into a proper domain service.

### New module

- Add [backend/balancer-service/src/services/balance_run.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/services/balance_run.py)

Suggested functions:

- `create_run(session, tournament_id, workspace_id, config_json, input_snapshot_json, actor)`
- `mark_run_started(session, run_id, actor=None)`
- `append_run_progress(session, run_id, stage, progress, message)`
- `append_run_variant(session, run_id, variant_payload, statistics, objective_score=None, is_final=False)`
- `mark_run_completed(session, run_id, final_variant_ids)`
- `mark_run_failed(session, run_id, error_text)`
- `select_variant(session, run_id, variant_id, actor)`
- `save_selected_variant(session, run_id, actor)`
- `export_saved_result(session, run_id_or_balance_id, actor)`

### Existing code to reuse

- `save_balance()` and `export_balance()` from [backend/balancer-service/src/services/admin/balancer.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/services/admin/balancer.py)
- `sync_balance_variants_and_slots()` from [backend/balancer-service/src/services/admin/balancer_dual_write.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/services/admin/balancer_dual_write.py)
- `create_balance_snapshot()` from [backend/balancer-service/src/services/admin/balance_analytics.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/services/admin/balance_analytics.py)

### Data flow rule

The new source of truth should become:

- `balance_run`
- `balance_run_variant`

Then the selected or final variant can be materialized into `BalancerBalance` for compatibility and analytics export.

## Phase 5: API Changes in balancer-service

Introduce a new run-oriented API alongside the old endpoints.

### New route module

- Add [backend/balancer-service/src/routes/runs.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/routes/runs.py)

### Suggested endpoints

- `POST /runs`
- `GET /runs/{run_id}`
- `GET /runs/{run_id}/variants`
- `POST /runs/{run_id}/select-variant`
- `POST /runs/{run_id}/save`
- `POST /runs/{run_id}/export`
- `POST /runs/{run_id}/cancel`
- `GET /workspaces/{workspace_id}/runs/active`
- `GET /tournaments/{tournament_id}/runs`

### Expected behavior

- `POST /runs` creates a `balance_run`, emits `balance.run.created`, and enqueues worker execution
- `GET /runs/{id}` returns server-side run state from Postgres
- `save/export` operate on the selected variant

### Compatibility period

Keep the following in [backend/balancer-service/src/views.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/views.py) for a transition period:

- `/jobs`
- `/jobs/{job_id}`
- `/jobs/{job_id}/result`
- `/jobs/{job_id}/stream`

These should gradually become adapters over the new `balance_run` layer instead of remaining Redis-only flows.

## Phase 6: Worker Migration

Update the worker in [backend/balancer-service/serve.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/serve.py) so that it writes progress and results into persistent run state.

### Changes

1. Change queue payload to carry `run_id` instead of only `job_id`
2. On start:
- load `balance_run`
- call `mark_run_started`
- publish `balance.run.started`
3. Convert progress callback writes from Redis events to:
- persistent progress events in Postgres
- pub/sub fan-out
4. Save variants into `balance_run_variant`
5. Complete the run through `mark_run_completed`

### Algorithm note

- Genetic already emits progress through callback in [backend/balancer-service/src/service.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/service.py)
- CP-SAT in [backend/balancer-service/src/cpsat_bridge.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/cpsat_bridge.py) currently returns solutions only at the end and should be extended later if intermediate variants are needed live

## Phase 7: WebSocket Gateway in parser-service

Implement the shared workspace gateway in `parser-service`.

### New route

- Add [backend/parser-service/src/routes/realtime.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/routes/realtime.py)

Endpoint:

- `@router.websocket("/ws/workspaces/{workspace_id}/realtime")`

### Auth

Extend [backend/parser-service/src/core/auth.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/core/auth.py) with:

- `get_websocket_user_required`
- `require_websocket_workspace_member`

### Connection manager

- Add [backend/parser-service/src/services/realtime/workspace_ws.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/services/realtime/workspace_ws.py)

Suggested structures:

- `_connections_by_workspace: dict[int, set[WebSocket]]`
- optional socket filters:
- `domains`
- `tournament_id`
- `after_event_id`

Suggested methods:

- `connect(workspace_id, websocket, subscription)`
- `disconnect(workspace_id, websocket)`
- `send_snapshot(websocket, snapshot)`
- `send_event(websocket, envelope)`
- `broadcast(workspace_id, envelope)`

### Reconnect flow

Client sends:

- `token`
- `after_event_id`
- optional `domain`
- optional `tournament_id`

Server performs:

1. auth and workspace membership check
2. `accept`
3. send snapshot
4. send replay after `after_event_id`
5. subscribe to live transport

### Live transport into gateway

Add a startup listener in parser-service:

- Add [backend/parser-service/src/services/realtime/pubsub_listener.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/services/realtime/pubsub_listener.py)

This listener consumes Redis pub/sub notifications and fans them out to active workspace sockets.

## Phase 8: Frontend Realtime Client

Move the frontend away from page-local job subscriptions.

### New modules

- Add [frontend/src/services/realtime.service.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/services/realtime.service.ts)
- Add [frontend/src/hooks/useWorkspaceRealtime.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/hooks/useWorkspaceRealtime.ts)
- Add [frontend/src/stores/realtime.store.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/stores/realtime.store.ts)
- Add [frontend/src/types/realtime.types.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/types/realtime.types.ts)

### `realtime.service.ts`

Model it after [frontend/src/services/captain.service.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/services/captain.service.ts):

- build parser WebSocket URL
- pass `token` in query param
- pass `workspace_id`
- pass `after_event_id`
- handle reconnect

### `useWorkspaceRealtime.ts`

Responsibilities:

- connect and disconnect
- heartbeat and connection state
- replay cursor management
- dispatch incoming events into store or query invalidation

### `realtime.store.ts`

Suggested state:

- `lastEventIdByWorkspace`
- `connectionState`
- `activeRunsByTournament`
- `latestBalancerEvents`
- `selectedVariants`
- `savedBalances`

### Balancer migration

Update [frontend/src/app/balancer/page.tsx](/c:/Users/andre/Programming/anak-tournaments/frontend/src/app/balancer/page.tsx) so that:

- it subscribes to workspace realtime
- it reads active run state from the realtime store
- it updates UI from events rather than the local `jobState` reducer

Update [frontend/src/app/balancer/_components/useBalancerMutations.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/app/balancer/_components/useBalancerMutations.ts) so that:

- `runBalanceMutation` becomes a pure command that calls `POST /runs`
- the page reacts to WebSocket events for progress and results

## Phase 9: Compatibility Window

Avoid a big-bang switch.

### During migration

- Keep current `SSE + Redis job_store`
- Add `balance_run + workspace_event + WebSocket` in parallel
- Optionally guard the new UI path behind a feature flag

### Switch order

1. New backend run model
2. Worker dual-write
3. WebSocket gateway
4. Frontend hidden subscription
5. Enable WS-driven balancer UI
6. Remove old `/jobs/{id}/stream`
7. Stop treating Redis result as the primary data source

## Phase 10: Concrete File Plan

### Backend shared

- Add [backend/shared/models/realtime.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/models/realtime.py)
- Add [backend/shared/schemas/realtime.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/schemas/realtime.py)
- Add [backend/shared/services/realtime_store.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/services/realtime_store.py)
- Add [backend/shared/services/realtime_publisher.py](/c:/Users/andre/Programming/anak-tournaments/backend/shared/services/realtime_publisher.py)

### Balancer service

- Add [backend/balancer-service/src/services/balance_run.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/services/balance_run.py)
- Add [backend/balancer-service/src/routes/runs.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/routes/runs.py)
- Update [backend/balancer-service/serve.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/serve.py)
- Update [backend/balancer-service/main.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/main.py)
- Keep but gradually deprecate [backend/balancer-service/src/views.py](/c:/Users/andre/Programming/anak-tournaments/backend/balancer-service/src/views.py)

### Parser service

- Add [backend/parser-service/src/routes/realtime.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/routes/realtime.py)
- Add [backend/parser-service/src/services/realtime/workspace_ws.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/services/realtime/workspace_ws.py)
- Add [backend/parser-service/src/services/realtime/pubsub_listener.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/services/realtime/pubsub_listener.py)
- Update [backend/parser-service/src/core/auth.py](/c:/Users/andre/Programming/anak-tournaments/backend/parser-service/src/core/auth.py)
- Update parser main app to start the listener and include the route

### Frontend

- Add [frontend/src/services/realtime.service.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/services/realtime.service.ts)
- Add [frontend/src/hooks/useWorkspaceRealtime.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/hooks/useWorkspaceRealtime.ts)
- Add [frontend/src/stores/realtime.store.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/stores/realtime.store.ts)
- Add [frontend/src/types/realtime.types.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/types/realtime.types.ts)
- Update [frontend/src/app/balancer/page.tsx](/c:/Users/andre/Programming/anak-tournaments/frontend/src/app/balancer/page.tsx)
- Update [frontend/src/app/balancer/_components/useBalancerMutations.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/app/balancer/_components/useBalancerMutations.ts)
- Eventually remove the balancer-specific SSE path from [frontend/src/services/balancer.service.ts](/c:/Users/andre/Programming/anak-tournaments/frontend/src/services/balancer.service.ts)

## Validation Plan

### Backend

- Test `create_run -> worker -> progress -> variant -> completed`
- Test one active run per tournament
- Test `select/save/export` emits correct persistent events
- Test reconnect replay by `after_event_id`
- Test gateway filters by workspace and tournament

### Frontend

- User A starts a run and user B sees all updates live
- User B opens later and gets active state from snapshot
- Socket reconnect restores state through replay
- Final result appears without manual refresh
- Save and export by one user update the other user's UI

### Rollout safety

- Keep old `job_id` endpoints until the new UI is stable
- Compare `balance_run` state and legacy `job_store` during migration
- Add metrics for WebSocket connections, replay lag, and event publish failures

## Recommended Delivery Sequence

1. Migration and models
2. Event envelope and publisher
3. `balance_run` service
4. Worker dual-write
5. Parser realtime gateway
6. Frontend realtime client
7. Switch balancer page to WS-driven state
8. Deprecate old SSE and Redis-only result flow
