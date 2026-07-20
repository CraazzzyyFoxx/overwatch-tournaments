# Parser Service

Ingests and parses Overwatch match logs into OWT's shared domain models, fetches player ranks, and
runs scheduled/event-driven processing.

- **Type:** headless FastStream (RabbitMQ) RPC worker + event consumers + APScheduler — no HTTP
  server of its own
- **Entry point:** `serve.py`
- **Run:** `faststream run serve:app`
- **CLI:** `backfill_impact.py` (MVP-impact backfill)
- **Reached via:** the Go gateway (the sole HTTP entry point) under `/api/v1`

See [`../../docs/architecture.md`](../../docs/architecture.md) for the system overview.

## Responsibilities

The RPC surface is grouped as representative `rpc.parser.*` methods served behind the gateway:

- **Match-log ingestion** — parse and normalize match-log data into the [`shared/`](../shared/README.md)
  models.
- **Event consumers** — upload + process match-log (durable job channel), achievement evaluate,
  tournament encounter-completed, rank fetch (+ priority), and registration-approved rank check.
- **OverFast rank fetch** — a Redis leader-locked APScheduler that fetches player ranks from the
  external OverFast API (via the outbound proxy).
- **Typed reads / admin** — parser-unique reads and admin operations (logs, rank, achievements,
  misc, bootstrap, impact).

> **Note:** `ortools` is declared as a dependency but is not currently used (never imported); there
> is no OR-Tools optimization in this service.

## Dependencies

- **Postgres** — shared ORM (matches / overwatch_rank / log_processing schemas).
- **Redis** — scheduler leader lock and caching.
- **RabbitMQ** — RPC transport, event consumers, and durable job queues.
- **S3** — match-log storage.
- **External OverFast API** — rank data, reached via the outbound proxy.

## Configuration & environment

See `backend/env/parser.env`, which inherits `backend/env/common.env`. An outbound proxy can be
configured (`PROXY_HOST` / `PROXY_PORT`) for fetching external data (e.g. OverFast).
