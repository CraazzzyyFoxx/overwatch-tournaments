# Analytics Service

Post-tournament analytics for OWT. It owns all analytics computation and the `analytics`
Postgres schema. See [`../../docs/architecture.md`](../../docs/architecture.md) for how it
fits into the wider platform.

The service ships as **two headless FastStream (RabbitMQ) processes** — there is no HTTP
server, no `main.py`, and no uvicorn/port `8006`. External traffic reaches it as
`/api/analytics/*` through the Go gateway, which translates each route to its
`rpc.analytics.*` queue.

## Processes

| compose service | entry point | run command | responsibility |
|---|---|---|---|
| `analytics-svc` | `serve_rpc.py` | `faststream run serve_rpc:app` | Light RPC layer: hosts every `rpc.analytics.*` subscriber (public/auth reads, light mutations, and job-control that enqueues to the heavy worker). |
| `analytics-worker` | `serve.py` | `faststream run serve:app` | Heavy compute: consumes the `analytics_job` / `analytics_train` / `analytics_infer` queues, runs the balance-snapshot domain-event consumer, and runs the APScheduler nightly drift check. |

The split is deliberate: `serve_rpc.py` must **not** import `serve` or subscribe to the
`ANALYTICS_*` job queues, or those durable queues would be double-owned and messages
would round-robin between the two processes. Do not scale `analytics-worker` (its
APScheduler drift job would multi-fire).

- **Job-control (analytics-svc):** RPC create/status/result methods enqueue work to the
  heavy queues; status and results live in the `AnalyticsJob` table, with live progress
  pushed over Redis (`workspace:{id}:analytics_jobs`) and relayed to WebSocket clients
  by the gateway.
- **Balance-snapshot consumer (analytics-worker):** balancer-service emits
  `balancer.balance.exported` via its outbox → `analytics_balance_snapshot` queue →
  analytics-worker writes `analytics.balance_snapshot` + `balance_player_snapshot`.
- **Nightly drift check (analytics-worker):** APScheduler cron at 03:30 UTC computes
  per-feature Wasserstein drift against a recent tournament window and emits a Sentry
  breadcrumb when a feature crosses the threshold.

## Scope

- **v1:** OpenSkill / Plackett-Luce rating shifts, linear/points algorithms, and
  predicted standings.
- **v2:** a classical-ML pipeline — LightGBM/XGBoost gradient boosting + Bayesian layer +
  Monte Carlo — for player performance, shifts, predicted standings, and match quality.
  v2 is **implemented and wired** (`analytics_train` / `analytics_infer` queues,
  `MLFeatureStore` / `MLModelArtifact`, and `AnalyticsStandingsDistribution` as the sole
  predicted-place source), not merely planned.

## GPU worker

Heavy ML training/inference can run on GPU. Build `analytics-worker` from
[`../analytics-worker.gpu.Dockerfile`](../analytics-worker.gpu.Dockerfile) and layer the
`docker-compose.gpu.yml` override (thin NVIDIA device reservation for `analytics-worker`
only) over the base stack.

## Local run

```bash
# Light RPC service (reads / mutations / job-control)
faststream run serve_rpc:app

# Heavy compute worker (ML queues + balance-snapshot consumer + drift scheduler)
faststream run serve:app
```

## Operations

Shift/model recompute procedures live in the ops runbook:
[`docs/runbook-shift-recompute.md`](docs/runbook-shift-recompute.md).

## Dependencies

- **Postgres** — the `analytics` schema.
- **Redis** — job-progress realtime pub/sub.
- **RabbitMQ** — RPC transport and the `analytics_job` / `analytics_train` /
  `analytics_infer` job queues.
- **ML libraries** — OpenSkill, LightGBM/XGBoost, and the Bayesian/Monte-Carlo stack.

## Configuration & environment

See `backend/env/analytics.env`, which inherits `backend/env/common.env`.
`WORKER_METRICS_PORT` exposes Prometheus metrics only — it is not an HTTP API.
