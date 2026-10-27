# Analytics Service (`analytics-svc` + `analytics-worker`)

Post-tournament analytics for OWT: rating shifts, per-player performance, placement
distributions, encounter quality and player anomalies. It is the authority for the
`analytics` Postgres schema and for the ML model registry that produces those numbers.
See [`../../docs/architecture.md`](../../docs/architecture.md) for how it fits into the
wider platform.

This directory builds **one image that runs as two headless FastStream (RabbitMQ)
processes**. Neither serves HTTP. External traffic arrives as `/api/analytics/*` at the Go
gateway, which translates each route into a request/reply RPC call on `rpc.analytics.*`
with an `x-deadline-ms` budget and expects an `{ok, data, error}` envelope back.

The split exists because an RPC reply must fit inside that deadline and ML training does
not — a backfill runs for many minutes. So:

- `analytics-svc` may read, apply light mutations, and **create** jobs; it must not run
  ratings recomputation, training, or inference, and must not import `serve` or subscribe
  to the `ANALYTICS_*` queues (those durable queues would then be double-owned and
  messages would round-robin between the two processes).
- `analytics-worker` may take as long as it needs; it never answers an RPC call.

| | `analytics-svc` | `analytics-worker` |
|---|---|---|
| **Entry point** | `serve_rpc.py` | `serve.py` |
| **Run command** | `faststream run serve_rpc:app` | `faststream run serve:app` |
| **Compose profile** | default | `workers` |
| **Transport** | RabbitMQ request/reply (`rpc.analytics.*`); no HTTP | RabbitMQ durable job queues; no HTTP |
| **Metrics** | Prometheus on `WORKER_METRICS_PORT` (dev 9107, prod 9108) | Prometheus on `WORKER_METRICS_PORT` (dev 9106, prod 9106) |
| **Resources (compose)** | 1 CPU / 512M | 8 CPU / 4G, `/opt/owt/models` + feature-cache volumes |

Prometheus scrapes `analytics-svc:9108`. In `docker-compose.yml` the dev block sets
`WORKER_METRICS_PORT=9107`, so dev scraping of `analytics-svc` does not work; production
sets 9108 and is consistent. This is a defect, not a convention.

## Responsibilities

- **Rating shifts** — the Points, Linear and OpenSkill (Plackett-Luce) algorithms that turn
  tournament results into per-player division shifts, each stored with its posterior sd
  (`shift_sd`); the read API turns `(shift, shift_sd)` into a probability-gated division
  forecast (`src/domain/`, `src/services/analytics/`). Recalculating a tournament also rewrites
  the v1 rows of every later tournament of its workspace that already has them.
- **ML signals** — LightGBM/XGBoost with a Bayesian layer and Monte Carlo simulation, for
  player performance, shift v2, predicted standings, match quality and player anomalies
  (`src/services/ml/`). `analytics.standings_distribution` is the only source of placement
  predictions; a scalar "predicted place" is the rounded mean, derived at read time.
- **Model lifecycle** — training, calibration, backtesting, drift measurement, and the
  artifact registry that marks one artifact active per model kind.
- **Recompute orchestration** — one `AnalyticsJob` row per recomputation, its staged
  progress, its terminal status and its result summary.
- **Anomaly review** — reviewer verdicts on flagged performances, unique per
  `(tournament, player, kind)`, so a reviewed anomaly is not raised again on recompute.

Analytics never ingests: match logs and tournament results are owned upstream. It only
derives numbers from what is already in the database.

## Interface

`analytics-svc` subscribes to the `rpc.analytics.*` namespace. Method groups:

| Group | What it covers |
|---|---|
| Algorithm reads | The `analytics.algorithms` registry that every derived number points at. |
| Signal reads | Tournament analytics, streaks, performance, standings distributions, match quality, player anomalies, per-player explanations. |
| Artifact reads | ML model artifacts, optionally filtered to the active one per kind. |
| Job reads | Active job, recent job list, single job by id. |
| Light mutations | Manual shift override and anomaly-feedback upsert. |
| Job control | Create a job (`compute` or `train_ml`), plus the `recalculate` and `points` wrappers that create a scoped `compute` job. |

The full method list with request/response schemas is published at `/api/docs`, generated
from `src/openapi_schemas.py` (`OPERATIONS`) and `src/openapi_docs.py` (`DOCS`).

**Durable queues consumed** — by `analytics-worker` only, all declared in
`shared/messaging/config.py` with a `dlx` dead-letter exchange and a per-queue message TTL:

| Queue | Payload | Runs | TTL |
|---|---|---|---|
| `analytics_job` | `AnalyticsJobRequested` (job id only) | The unified pipeline: dispatch by `AnalyticsJob.kind` to ratings recompute + ML inference (`compute`) or training (`train_ml`) | 1 h |
| `tournament_state_changed` (bound to `tournament.events`, key `tournament.state.changed`) | `TournamentStateChangedEvent` | A tournament that becomes `completed` gets a `compute` job (`src/worker/tournament_events.py`): the `create_job` gates minus the actor, skipped and acked for an unverified workspace or an active job | 5 min |

Each has a matching `<queue>.dlq`, declared by `analytics-worker` at startup.

**Dispatch** — every request event above that analytics sends (`AnalyticsJobRequested`) is an
outbox row written in the request's own
transaction (for a job, the same one that creates the row), relayed by the
`event_outbox_drain` tick that both processes run every second.

**Realtime** — `analytics-worker` publishes job lifecycle events (`analytics_job.<status>`,
carrying staged progress and any error) to the `workspace:{id}:analytics_jobs` topic. Each
event is persisted as a `realtime.workspace_event` row and pushed to Redis; the gateway
fans it out to WebSocket clients. Events are workspace-scoped — a job with no
`workspace_id` publishes nothing. Redis being unavailable degrades to "no progress
events", not to a failed job.

**Scheduled work** — `analytics-worker` runs one APScheduler cron job, `nightly_drift_check`
at 03:30 UTC: it builds a feature frame over the last 10 tournaments, computes per-feature
Wasserstein drift, and emits a Sentry breadcrumb when any feature crosses the threshold.
Both processes also run the 1 s `event_outbox_drain` (safe on any number of replicas).

The service publishes no domain events of its own.

## Data owned

Writes the whole `analytics` schema: `algorithms`, `player_shift`, `shifts`, `performance`,
`standings_distribution`, `match_quality`, `player_anomaly`, `anomaly_feedback`,
`ml_model_artifact`, and `job`. Every derived row is keyed on `algorithm_id`, so two
algorithms can hold different opinions about the same `(tournament, player)` without
overwriting each other. It also writes `realtime.workspace_event` rows for job progress and
`event_outbox` rows for its queue dispatches.

Reads, never writes: `tournament` (the `tournament.player` roster slot that every number is
anchored on, plus teams and standings), native `stats` observations through their bound
`encounter.game`, `registration`, `tenancy`, and `division_grid` (for canonical division
resolution). Match features and match-quality scores retain observed `source_position`
home/away orientation, not encounter slot order. Roster roles/ranks remain the trained
input boundary; observed snapshots do not replace registration context.

Concrete features, models and the canonical division scale belong to the discipline module
(`shared/disciplines/overwatch/analytics/`); this service reaches them only through
`DisciplineSpec.analytics` (`src/core/analytics_exports.py`) and keeps the feature cache, the
OpenSkill replay, device selection, artifact storage and the registry/jobs/orchestration.

**Discipline, role and algorithm scope.** The tournament that owns a request (the training cutoff, the tournament
to infer or back-test) decides which module runs; no code path defaults to a game. Its discipline cuts the history,
split, feature, rating-replay and cache-key scope (a feature-cache entry is keyed on discipline, feature version,
namespace and the existing workspace/tournament parameters). A cutoff of another discipline, or outside the
requested workspace allowlist, is rejected. An artifact belongs to the discipline whose module declares its algorithm
name and kind (`AnalyticsExports.MODELS`); a role artifact also sits on a rated role of that discipline, so
another algorithm sharing a kind and another game's same-code role (`support`) are never registered, activated or
loaded. A discipline that declares no analytics module (LoL) offers no algorithm, returns an empty summary from
automatic enrichment without a single write, and answers explicit train/infer/model requests with 422 before a job is
admitted or quota is charged. The CLI takes an optional `--discipline` that must agree with the tournament; a
`backtest` without `--cutoff` and an `evaluate` without `--from`/`--to` require it, and `backfill` visits only
existing, non-hidden, supported tournaments.

**Measuring the shift methods.** `backtest` trains, activates and infers for real inside a transaction it rolls back,
with fold artifacts in a removed temporary directory, and scores the v2 shift and its baselines (no move, Points,
Linear, OpenSkill) by their agreement with the organizers' realised moves — what organizers did, not ground truth.
That transaction stays open across every fold's model fits, which pgBouncer ends after 60 s idle: run `backtest` on a
direct connection (`-e POSTGRES_HOST=postgres -e POSTGRES_PORT=5432 -e DB_PGBOUNCER=false` on the bundled database).
`evaluate` is read-only and scores the levels each method implies (organizer rank, no move, previous rank minus the
stored shift) on who wins the duel encounters of the next tournament: per method k of P(home wins) = σ(−k·Δlevel),
log-loss, Brier, AUC and coverage of stored rows.

The P4 regression oracle (`tests/fixtures/stats_feature_parity.json`) covers all six
feature/profile families and the actual aligned main/coarse predictor inputs; it supplies no
fitted artifact. The frozen pre-move evidence for quantile execution, standings/shift prediction
frames and the predictions of small fitted fixture estimators is
`tests/fixtures/ml_prediction_parity.json` with the estimator state and provenance in
`tests/fixtures/ml_pre_move/`; it was captured once under the pre-move code and is never
regenerated.

### Artifact class move: explicit two-image conversion

`PerformanceModelV2`, `_ConstantClassifier`, `WinProbabilityModel` and `ShiftModelV2` moved into
`shared.disciplines.overwatch.analytics.models.*`. The runtime keeps **no** old-path alias, so every
serialized artifact (active **and** historical) is converted in a maintenance window by
`scripts/convert_discipline_artifacts.py` (`export` → `stage` → `apply`, plus `rollback`); see
`docs/runbook-shift-recompute.md` for the steps. Nothing is retrained or refit; originals and
their SHA256 are never modified. The tool is covered by `tests/test_artifact_discipline_conversion.py`
against the pre-move pickles in `tests/fixtures/ml_pre_move/`. A real deployment inventory,
export, stage and apply belong to P9 (retained old image, same pinned numerical libraries,
workers/training/cache writers stopped); an artifact of an unsupported class or state blocks the
release until an explicit conversion case is implemented and reviewed.

`tests/test_discipline_runtime_smoke.py` runs the whole chain once on a scratch PostgreSQL clone: export under the
archived pre-move source, stage, `apply`, then the runtime's own registry selection and `run_for_tournament`
(performance, shift, standings, anomalies, match quality and its standings loader) as a non-owner role with no USAGE on
the retained legacy schemas. Every frozen D96 receipt is reproduced bit-for-bit by the registry-loaded models, every
table written equals the one written from an independently assembled registry (the Monte Carlo
`standings_distribution` included, compared exactly under a seeded test RNG), LoL resolves to no artifact, no module (`UnsupportedAnalytics`) and
no read or write, and `rollback` restores the original URI set. This is fixture proof only; production artifacts are
never described as converted until P9 has run the procedure on its real inventory.

Migrations are central — there is one Alembic project at `backend/migrations/` and this
service ships none. Entity diagrams and column-level detail:
[`../../docs/database_erd.md`](../../docs/database_erd.md#analytics--analytics).

## Dependencies

- **PostgreSQL** — the shared database; the `analytics` schema plus the read-only sources
  above.
- **RabbitMQ** — RPC transport for `analytics-svc` and the three durable job queues for
  `analytics-worker`.
- **Redis** — realtime job-progress pub/sub only. Optional at the worker: a failed
  connection disables events and is logged, not fatal.
- **Filesystem** — trained artifacts under `ANALYTICS_MODELS_DIR` (the `analytics-models`
  volume) and the feature cache under `ANALYTICS_FEATURE_CACHE_DIR`. Both are worker-only
  mounts.

No external API calls, so no `proxy` egress.

## Configuration

`backend/env/analytics.env`, layered over `backend/env/common.env`. Both processes load
both files; compose then overrides per process.

Settings that change behaviour:

- `ANALYTICS_MODELS_DIR` — artifact storage root. Worker writes it, both processes read it.
- `ANALYTICS_FEATURE_CACHE_ENABLED` / `_DIR` / `_NAMESPACE` / `_TTL_SECONDS` — file-backed
  cache for expensive feature frames. Not a source of truth: bump the namespace or clear
  the directory after changing feature logic or reprocessing historical logs.
- `ML_TRAIN_DEVICE` (`auto` | `cpu` | `cuda` | `gpu`) and `ML_GPU_FALLBACK` — training
  accelerator and whether GPU failures fall back to CPU.
- Shift-model tuning in `src/core/config.py` (`SHIFT_W_TEAM`, `SHIFT_W_OS`, the
  rank-dependent `SHIFT_INDIV_*` scales and clamps, `SHIFT_DOMINANCE_*`,
  `SHIFT_PLACEMENT_FLOOR`, `SHIFT_CLAMP_TOP_GRID_REF`) and `STANDINGS_PROB_SHARPENING`.
  Each carries a comment saying whether it applies at read time or needs a retrain to take
  effect — most need a retrain.
- `LINEAR_SHIFT_SCALE` and `SMURF_STRONG_LOCAL_Z` / `SMURF_MVP_DOMINANCE` — v1 linear scale
  (applied at read time; recompute v1 shifts to refresh stored rows) and the smurf flag
  thresholds.
- `FORECAST_CONFIDENCE_THRESHOLD` (0.8) — the probability a climb/drop needs before the
  forecast shows it; applied at read time, no recompute.
- `WORKER_METRICS_PORT` — Prometheus exposition only, not an API.
- `RPC_PREFETCH_COUNT` (default 16) — how many gateway RPC handlers `analytics-svc` runs at once (a
  process-wide permit pool, `shared.rpc.deadline.configure_rpc_concurrency`), and each RPC consumer's
  AMQP prefetch (QoS is per consumer, not per channel). The worker uses the broker default.

## Running

```bash
cd backend/analytics-service

# Light RPC service: reads, light mutations, job creation
faststream run serve_rpc:app

# Heavy compute worker: job queues + nightly drift check
faststream run serve:app
```

Under compose, `analytics-svc` starts by default; `analytics-worker` is behind the
`workers` profile:

```bash
docker compose --profile workers up -d analytics-worker
```

Both healthchecks in `docker-compose.production.yml` are `python -c "import sys; sys.exit(0)"`
— they prove the interpreter runs, not that the broker is connected.

**GPU.** `docker-compose.gpu.yml` overrides `analytics-worker` alone: it swaps the image to
one built from [`../analytics-worker.gpu.Dockerfile`](../analytics-worker.gpu.Dockerfile),
sets the `ML_TRAIN_DEVICE` / `ML_GPU_FALLBACK` / `NVIDIA_*` variables, and reserves all
NVIDIA devices. `analytics-svc` is untouched — it never trains.

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml --profile workers \
  up -d --build analytics-worker
```

## Operational notes

- **One active job per workspace.** `JobService` refuses a second create while one is
  `pending` or `running` and raises `JobConflict`, which job-control returns as `409`.
  Before answering "is a job active", the service reconciles rows whose progress contains a
  failed stage but whose status is still active.
- **Dispatch rides the outbox.** A job row and its `AnalyticsJobRequested` commit together, so
  no crash leaves a `pending` job with nothing to run it; with the broker down the event waits
  in `event_outbox` and the job stays `pending` until the drain relays it.
- **Failure is recorded, not retried.** `run_job` catches, rolls back, writes the stage
  detail plus a truncated traceback onto the row, emits a `failed` realtime event, and
  returns — the message is acked. Delivery is at-least-once, so `run_job` skips (acks and
  logs) a replayed event for a job that already `succeeded` or `failed`; a redelivered
  `running` job is run again, since on the single worker that means the attempt that marked
  it died with its connection. Recovery means creating a new job. A training job commits before
  each model fit (no transaction idles across a fit), so the artifacts it registered before a
  failure stay active. Messages that do dead-letter (TTL expiry, broker-side nack, a
  `tournament_state_changed` handler error) land on `<queue>.dlq`.
- **Do not scale `analytics-worker`.** APScheduler runs in-process with no leader lock, so
  a second replica multi-fires the nightly drift check. Replicating `analytics-svc` is
  fine.
- **Cost traps.** Training builds feature frames across every tournament up to the cutoff;
  the feature cache is what keeps that tolerable, and clearing it makes the next training
  run far more expensive.
- **Compute rebuilds its frames.** A compute job runs inference under
  `refreshing_feature_cache()`, so it never reads a frame cached before the job and sees
  results corrected after the tournament; training and backfill keep using the cache.

Shift and model recompute procedures live in
[`docs/runbook-shift-recompute.md`](docs/runbook-shift-recompute.md).
