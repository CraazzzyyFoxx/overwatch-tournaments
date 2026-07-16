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

Deliberately **not** load tested:

- `/api/auth/*` — nginx rate-limits it to 10 r/s per IP; from a single
  generator you would only measure the limiter.
- WebSockets (`/ws`, `/api/realtime/ws`) and admin/write endpoints.

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

## Interpreting results

- Watch p95/p99 per endpoint group (URLs are grouped, e.g. `/api/v1/tournaments/[id]`).
- First-hit latency on statistics endpoints is the cold-cache cost; repeats
  measure the Redis cache path. Restart Redis between runs to re-measure cold.
- `429` responses count as failures — if you see them outside `/api/auth/`,
  you are hitting the gateway's per-IP token bucket; distribute workers
  across hosts for higher aggregate load.
- Grafana dashboards (`make monitoring-up`) show the server-side view
  (RabbitMQ queue depth, worker latency, DB pool saturation) during a run.
