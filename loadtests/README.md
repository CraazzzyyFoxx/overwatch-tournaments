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
  which lives in its own locustfile precisely because it writes, and which holds
  a real socket per simulated seat.

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
| `OWT_DRAFT_ROOM` | `.draft-room.json` | **Draft scenario:** the room `draft_seed.py` wrote: its ids and every seat's token (gitignored) |
| `OWT_DRAFT_PICK_INTERVAL` | `10` | **Draft scenario:** seconds between the driver's autopicks, i.e. the event rate the room reacts to |
| `OWT_DRAFT_ROLLBACK_AFTER` | _(none)_ | **Draft scenario:** after this many picks the driver rolls the last one back (every client re-reads the board) and resumes |
| `OWT_DRAFT_CHAT_EVERY` | `60` | **Draft scenario:** seconds between one captain's chat messages; `0` keeps the room silent |
| `OWT_DRAFT_ORIGIN` | the target host | **Draft scenario:** `Origin` of the simulated tabs; the gateway refuses sockets from origins outside `GATEWAY_WS_ALLOWED_ORIGINS` |
| `OWT_DRAFT_PSQL` | psql in the e2e stack's Postgres | **Draft scenario:** the command that runs one SQL statement on the target's database (`draft_seed.py` appends the statement), e.g. `docker exec db_postgres psql -U system -d owt_dev -tAc` on the dev site |
| `OWT_SOURCE_NET` | _(none)_ | **Draft scenario:** a network every simulated user takes its own source address from (`127.1.0.0/16` with the stack on the generator's host), so the per-IP limits along the path — traefik, nginx, the gateway — count one client per user, as in a real room; unset, every user shares the generator's address |

## Draft room scenario (`draft_locustfile.py`)

One live tournament draft with everyone in its room: the organizer, one
captain per team and the spectators, each a real client with its own
WebSocket. A separate locustfile because it **writes**: it creates accounts,
a tournament and a draft, then drives the draft to completion. Run it on the
isolated e2e stack (own tmpfs database), never on a database anyone uses.

| User class | Count | Behaviour |
| --- | --- | --- |
| `DraftDriver` | exactly 1 | The organizer's hands: autopicks the pick on the clock every `OWT_DRAFT_PICK_INTERVAL` s (reading the board first, as its own mutation would), and once, after `OWT_DRAFT_ROLLBACK_AFTER` picks, rolls back and resumes |
| `DraftOrganizer` | exactly 1 | The organizer's room; also re-reads feasibility whenever a pick lands |
| `DraftCaptain` | one per seeded team | Its own fit and queue on load and whenever an event moves its team, its pick options while it is on the clock, a chat message every `OWT_DRAFT_CHAT_EVERY` s |
| `DraftSpectator` | the rest | Logged in while the room has spectator accounts left, anonymous after; reads the room, then lives off the socket |

Every seat opens the page like `frontend/src/app/draft/[id]/page.tsx` (auth
bootstrap, workspaces, tournament overview, the tournament's draft lookup,
discipline metadata, workspace, chat history), subscribes to the board and
chat topics on `/api/v1/realtime/ws`, folds events like
`frontend/src/hooks/useDraftData.ts` (`draftDerivedScope`, the 250 ms
`DERIVED_FLUSH_MS`, `draftEventNeedsSnapshot`), polls the board every 120 s
while the draft is live (30 s while its socket is down), and reconnects like
`frontend/src/services/realtime.service.ts`: backoff with jitter, then a board
re-read, the derived reads and a chat catch-up.

```bash
# The stack, plus an overlay lifting the gateway's 64-anonymous-sockets-per-IP
# cap (every simulated spectator shares the generator's IP):
docker compose -p owt-e2e -f docker-compose.yml -f docker-compose.e2e.yml up -d --wait postgres
docker compose -p owt-e2e -f docker-compose.yml -f docker-compose.e2e.yml \
  run --rm --no-deps -v "$(pwd)/backend/migrations:/app/migrations" app-svc alembic upgrade head
docker compose -p owt-e2e -f docker-compose.yml -f docker-compose.e2e.yml \
  -f loadtests/docker-compose.draft.yml up -d --build --wait

cd loadtests
# A fresh room per run (the run finishes its draft): 20 teams, 90 pool players,
# 40 spectator accounts. Promotes its organizer with SQL in the e2e Postgres.
uv run python draft_seed.py --host http://127.0.0.1:8090 --teams 20 --spectator-accounts 40

# 20 captains + organizer + driver + 160 spectators joining at 6/s, an
# autopick every 3 s, one rollback after 30 picks.
OWT_DRAFT_PICK_INTERVAL=3 OWT_DRAFT_ROLLBACK_AFTER=30 OWT_DRAFT_ORIGIN=http://localhost:8090 \
  uv run locust -f draft_locustfile.py --host http://127.0.0.1:8090 --headless \
  -u 182 -r 6 -t 5m --csv draft --csv-full-history --html draft.html
```

`127.0.0.1`, not `localhost`: the e2e nginx listens on IPv4 loopback only, and
a client that tries `::1` first pays a fallback on every new connection, which
is every socket. For the reconnect herd, restart the gateway mid-run
(`docker restart owt-e2e-gateway-1`): every socket drops at once.

Reading the report:

- HTTP rows are the room's reads and writes, one per endpoint.
- `WS` rows: `connect` and `subscribe board|chat` latencies; `recv <event_type>`
  is the delivery delay of each frame (receipt minus the event's
  `occurred_at`; generator and stack share a clock), its count the frames the
  room received; `replay <event_type>` the events a resubscribe caught up on;
  `drop` one failure per socket that closed under its client.
- Failure messages end in `@t+N s` (10 s buckets from the start), so the error
  report says which phase each failure belongs to: the join wave, the
  rollback, the restart.
- `--csv-full-history` writes rolling 10 s percentiles per endpoint every
  second (`draft_stats_history.csv`): the p95 of one phase, not of the run.

Other room sizes: `draft_seed.py --teams 40 --out .draft-room-40.json`, then
`OWT_DRAFT_ROOM=.draft-room-40.json` and `-u 202` (40 captains, organizer,
driver, 160 spectators).

Local runs, Docker Desktop on Windows, the command above with a gateway restart
at 170 s. Before = the gateway with no draft cache and unthrottled presence,
the page reading the board twice, fit re-reading the shape and role weights
per team, pick options loading a snapshot of their own. Round 1 = all of that
fixed. Now = also pick options settled by Hall's condition (a forced matching
only for an unsafe option), the board built off the shared read snapshot, and
every committed board state prewarmed (board + snapshot) before the room
re-reads it. Herd = all clients re-reading at once (the rollback; the
reconnect after the restart).

| | 20 teams, before | 20 teams, round 1 | 20 teams, now | 40 teams, round 1 | 40 teams, now |
| --- | --- | --- | --- | --- | --- |
| HTTP errors outside the restart second | 202 (503 shed in the herds) | 0 | 0 | 0 | 0 |
| Board lookup p95, join wave | 190 ms | 130 ms | 59 ms | 720 ms | 49 ms |
| Board p95, rollback herd | 1.7 s | 870 ms | 940 ms | 1.6 s | 1.5 s |
| fit p95: between herds / rollback herd | 140 / 1400 ms | 51 / 480 ms | 24 / 460 ms | 250 / 1200 ms | 55 / 1200 ms |
| queue p95: between herds / rollback herd | 170 / 300 ms | 90 / 420 ms | 42 / 440 ms | 130 / 940 ms | 76 / 900 ms |
| pick options p95 | 160 ms | 100 ms | 80 ms | 390 ms | 210 ms |
| Pick event delivery p95 / p99 | 240 / 640 ms | 210 / 300 ms | 190 / 280 ms | 420 / 520 ms | 340 / 410 ms |
| Chat catch-up (`?after_id`) p95 | 1.4 s | 300 ms | 83 ms | 570 ms | 920 ms |
| Presence frames / delivery p95 | 38 213 / 550 ms | 3 204 / 100 ms | 3 371 / 45 ms | 3 981 / 81 ms | 4 147 / 100 ms |
| balancer CPU, join wave average | 35% | 13% | 11% | 28% | 16% |
| WS drops outside the restart | 0 | 0 | 0 | 0 | 0 |

The restart itself is about a second without a gateway: sockets that try to
reconnect inside it fail once and retry (120–200 failed connects per run), and
nothing fails after it.

The herd rows above are the generator's view, and in a herd the generator is
the bottleneck: one Locust process takes 200 board bodies (~190 KB each at 40
teams) at once, and each response waits its turn for that one core. The
gateway's access log (`duration_ms` per request) is the server's view of the
same seconds — at 40 teams the rollback board herd is p50 3 ms / p95 461 ms
there against p50 350 ms / p95 1.5 s in the report:

| Herd p95 at the gateway | 20 teams, now | 40 teams, now | 40 teams, 2 balancer replicas |
| --- | --- | --- | --- |
| Rollback: board / fit / queue | 579 / 217 / 222 ms | 461 / 357 / 253 ms | 763 / 417 / 434 ms |
| Reconnect: board / chat / fit / queue | 98 / 71 / 22 / 35 ms | 122 / 896 / 886 / 760 ms | 444 / 75 / 362 / 247 ms |

The rollback herd's critical path is one cold snapshot + board build (~0.4 s
at 40 teams), which a second replica does not shorten. The reconnect herd at
40 teams is a queue on the one event loop — 80 cold fit/queue reads (a pick
had just moved the state) plus ~80 logged-in chat catch-ups, whose envelope is
per viewer and so never shared — and a second replica (`--scale
balancer-svc=2`) cuts its chat and fit/queue 2–12×. That run shared the host
with other load (its join-wave lookup p95 was 1 s, against 50 ms alone), so
its board and rollback numbers are not comparable.

Roster engine: `RosterEngine.for_tournament`, the cold half of every snapshot,
reads plain Core rows — registrations, roles, identities, top characters and
members, with `= ANY(array)` binds — instead of ORM selectin chains, and its
output is unchanged (`shared/tests/test_roster_engine_reads_db.py`). One cold
load of the 40-team room's 210 seats, interleaved in one process: 55 → 26 ms
in the balancer container (asyncpg), 200 → 96 ms on the Windows host (psycopg;
135 → 82 ms at 26 teams). Two 40-team runs after it, against the run behind
the "40 teams, now" column:

| 40 teams | before | after: run 1 / run 2 |
| --- | --- | --- |
| Rollback board herd p95 at the gateway | 461 ms | 289 / 30 ms |
| Rollback fit / queue herd p95 at the gateway | 357 / 253 ms | 733 / 767, 465 / 492 ms |
| Reconnect chat / fit / queue p95 at the gateway | 896 / 886 / 760 ms | 496 / 363 / 564, 772 / 661 / 522 ms |
| Autopick p95 | 410 ms | 270 / 270 ms |
| Pick event delivery p95 | 340 ms | 220 / 210 ms |
| pick options p95 | 210 ms | 92 / 170 ms |

The fit/queue herds are 80 per-team computations queued on one event loop, not
roster loads; they move by ±300 ms between identical runs, so their
before/after difference is noise. Run 2 lost one board read client-side in the
rollback herd (status 0, no error at the gateway or nginx).

### Dev site (`dev.owt.craazzzyyfoxx.me` on `home`)

The same scenario against the dev deployment (`owt-dev-p4`: the production
compose at `PROD_SIZE=small`, a restored production database). The generator
ran on `home` itself, in a throwaway container with host networking and the
public hostname pinned to `127.0.0.1` (`--add-host`): every request took the
real path — TLS at traefik, the dev nginx, the gateway — without the WAN, and
`OWT_SOURCE_NET=127.1.0.0/16` gave every simulated user its own address. On
that edge this is not optional: traefik's `websecure` entrypoint limits every
client IP to 100 r/s (burst 50), and a first run from one address took 374
429s from it, all in the herds (182 board reads in the rollback alone). The
seeding is one client, so it went to the dev nginx directly, with
`OWT_DRAFT_PSQL="docker exec db_postgres psql -U system -d owt_dev -tAc"`, and
the gateway ran with `GATEWAY_WS_MAX_ANON_CONNS_PER_IP=0` and
`GATEWAY_AUTH_RATE_LIMIT=100000` for the duration (a throwaway compose
overlay). The seeded rows were deleted afterwards.

| Dev site | 20 teams | 40 teams |
| --- | --- | --- |
| HTTP errors outside the restart second / failed WS connects | 0 / 0 | 0 / 0 (one 502 inside it) |
| Board lookup p95, join wave | 34 ms | 53 ms |
| Rollback herd p95 at the gateway: board / fit / queue | 50 / 199 / 145 ms | 66 / 534 / 357 ms |
| Reconnect herd p95 at the gateway: board / chat / fit / queue | 14 / 99 / 92 / 89 ms | 6 / 246 / 215 / 241 ms |
| fit / queue p95, whole run | 110 / 140 ms | 390 / 240 ms |
| Autopick p95 / pick options p95 | 150 / 46 ms | 180 / 120 ms |
| Pick event delivery p95 / p99 | 130 / 150 ms | 160 / 260 ms |
| balancer CPU, join wave average / peak | 10% / 46% | 16% / 62% |

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
