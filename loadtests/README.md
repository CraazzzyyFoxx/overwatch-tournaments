# OWT Load Tests (Locust)

Load tests for the public API, hitting the **nginx → Go gateway** edge — the
same path production traffic takes (RabbitMQ RPC to the workers, Redis cache,
pgBouncer, all included).

## Traffic model

| User class | Weight | Behaviour |
| --- | --- | --- |
| `AnonymousBrowser` | 6 | Dashboard, tournament list/detail/stages/standings, encounters, matches, teams, cached metadata (heroes/maps/gamemodes/achievements) |
| `ProfileViewer` | 3 | Player profile tabs: profile, tournaments, heroes, maps summary, teammates, encounters, matches summary, player compare |
| `StatsAnalyst` | 2 | Statistics champion/winrate/won-maps, hero playtime + leaderboard, tournament statistics, analytics (algorithms, streaks, balance quality) |
| `SearchUser` | 2 | Type-ahead user search with 2–4 char prefixes of real player names |

Before the first user starts, the suite **seeds id pools** from the public
list/lookup endpoints (tournaments, users, heroes, matches, teams, encounters,
analytics algorithms), so detail endpoints are exercised with real ids instead
of measuring the 404 path. `404` on detail endpoints is still tolerated
(visibility gating / data drift); everything else non-200 counts as a failure.

Deliberately **not** load tested by this suite:

- `/api/auth/*` — nginx rate-limits it to 10 r/s per IP; from a single
  generator you would only measure the limiter.
- WebSockets (`/ws`, `/api/realtime/ws`) and admin/write endpoints. The one
  exception is the opt-in [draft room scenario](#draft-room-scenario-draft_locustfilepy),
  which lives in its own locustfile precisely because it writes.

## Prerequisites

The stack must be running with a populated database:

```bash
docker compose up -d --wait          # from the repo root
```

## Running

```bash
cd loadtests

# Web UI on http://localhost:8089 (defaults from locust.conf: host=http://localhost, 50 users)
uv run locust

# Headless: 100 users, ramp 10/s, 5 minutes, CSV + HTML report
uv run locust --headless -u 100 -r 10 -t 5m --csv results --html report.html

# Against another environment
uv run locust --headless -u 50 -r 5 -t 3m --host https://staging.example.com
```

Distributed (one master + N workers to saturate bigger targets):

```bash
uv run locust --master &
uv run locust --worker --processes 4
```

## Configuration (env vars)

| Variable | Default | Meaning |
| --- | --- | --- |
| `OWT_WORKSPACE_ID` | first workspace from `/api/v1/workspaces` | Pin all workspace-scoped requests to one workspace |
| `OWT_AUTH_TOKEN` | _(empty)_ | Optional JWT sent as `Authorization: Bearer …` (exercises the AuthOptional identity path) |
| `OWT_SEED_TIMEOUT` | `30` | Timeout (s) for the seeding requests |
| `OWT_SEED_POOL_SIZE` | `100` | Max ids kept per entity pool |
| `OWT_DRAFT_TOURNAMENT_ID` | _(none)_ | **Draft scenario:** tournament whose live draft to drive. Required by `draft_locustfile.py` |
| `OWT_DRAFT_TOKEN` | `OWT_AUTH_TOKEN` | **Draft scenario:** organizer JWT. Fit/queue/feasibility are AuthRequired and the autopick needs `team:create`, so one organizer token covers every simulated seat |
| `OWT_DRAFT_PICK_INTERVAL` | `10` | **Draft scenario:** seconds between the driver's autopicks, i.e. the event rate the room reacts to |
| `OWT_DRAFT_ORGANIZERS` | `1` | **Draft scenario:** how many viewers also re-read feasibility; the rest are plain captains |

## Draft room scenario (`draft_locustfile.py`)

A separate locustfile, because its driver **writes** (admin autopick) and must
never ride along with the read-only public suite. It reproduces the load shape
of the 2026-09-30 incident (`docs/incidents/2026-09-30`, "A · Перегрузка
драфта"): every captain and organizer in the room re-reads the server
derivations of the board after every pick.

| User class | Count | Behaviour |
| --- | --- | --- |
| `DraftDriver` | exactly 1 (`fixed_count`) | Reads the board, fires `POST /picks/{id}/autopick` with the current pick's `expected_version` every `OWT_DRAFT_PICK_INTERVAL` s, then bumps an in-process event counter |
| `DraftViewer` | the rest | One draft team each. Wakes on that counter, waits out the room's 250 ms coalescing window, then re-reads **fit + queue** for its team once per burst (never once per event); the first `OWT_DRAFT_ORGANIZERS` of them also re-read **feasibility**. Board polled every 120 s |

The counter stands in for the `pick_made` + `pick_started` burst the server
publishes on `tournament:{id}:draft`: locust runs every user as a greenlet in
one process, so a shared counter is the whole WS feed without a websocket
client. The read pattern itself mirrors `frontend/src/hooks/useDraftData.ts`
(`DERIVED_FLUSH_MS`, `BOARD_POLL_CONNECTED_MS`, `draftDerivedScope`).

Prerequisite: a **live** draft on the target tournament (status `live`, a pick
on the clock). The scenario drives it to completion — never point it at a real
draft anyone cares about, and never at production.

```bash
cd loadtests

# The incident's shape: 1 driver + 25 captains/organizers, a pick every 10 s
OWT_DRAFT_TOURNAMENT_ID=117 OWT_DRAFT_TOKEN=<organizer jwt> \
  uv run locust -f draft_locustfile.py --headless -u 26 -r 26 -t 5m \
  --csv draft --html draft.html
```

Reading the report: one row per draft endpoint
(`…/teams/[id]/fit`, `…/teams/[id]/queue`, `…/feasibility`,
`…/tournaments/[id]/draft`, `…/picks/[id]/autopick`). Since every viewer fires
its reads inside the same burst, the fit/queue p50 **is** the per-burst
latency, and p95 is the tail the slowest captain in the room saw.
Incident baseline for 26 teams / 130 players, for comparison:

| Where | fit/queue p50 |
| --- | --- |
| During the incident, before hotfix 2 | 8–15 s |
| After hotfix 2, 3 balancer replicas | ~2 s |
| After hotfix 2, 1 replica (the prod default) | 5–9 s |

## Interpreting results

- Watch p95/p99 per endpoint group (URLs are grouped, e.g. `/api/v1/tournaments/[id]`).
- First-hit latency on statistics endpoints is the cold-cache cost; repeats
  measure the Redis cache path. Restart Redis between runs to re-measure cold.
- `429` responses count as failures. Two limiters can produce them:
  - **nginx** (`req_edge` 40 r/s / burst 80, plus tighter zones on auth, WS and
    the upload paths).
    A run from the host against `http://localhost` reaches nginx over the docker
    bridge, i.e. from a private address, which the whitelist exempts — so local
    runs never see these and, by the same token, never exercise the limiter.
    Runs from a remote host will: distribute generators across source IPs.
  - **the gateway's** per-IP token bucket, for everything nginx let through.
- Grafana dashboards (`make monitoring-up`) show the server-side view
  (RabbitMQ queue depth, worker latency, DB pool saturation) during a run.
