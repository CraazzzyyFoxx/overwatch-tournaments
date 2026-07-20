# Backend

The OWT backend is a Python 3.13 monorepo of **headless [FastStream](https://faststream.ag2.ai/)
workers**. Each service is a long-running RabbitMQ RPC worker (not an HTTP server) that shares one
ORM/schema layer through [`shared/`](./shared/README.md). The **only** HTTP/WebSocket entry point is
the Go [`gateway/`](../gateway/README.md), which terminates HTTP, validates JWTs, and translates REST
routes into typed request/reply RPC over RabbitMQ (`rpc.<service>.<method>`) to these workers.

For the end-to-end request flow, edge topology, and data model see the system overview in
[`../docs/architecture.md`](../docs/architecture.md).

Dependencies are managed as a single [uv](https://docs.astral.sh/uv/) workspace rooted at this
directory; each service still keeps its own `pyproject.toml` as a workspace member.

## Services

| Service dir | Compose service | Kind | Purpose |
| --- | --- | --- | --- |
| [`app-service`](./app-service/README.md) | `app-svc` | RPC worker | Core public read/data API + workspace/user/metadata admin + binary assets |
| [`identity-service`](./identity-service/README.md) | `identity-svc` | RPC worker | AuthN/AuthZ: JWT, Discord OAuth, RBAC, workspace membership, custom domains/subdomains, API keys, player linking, service tokens, SSO |
| [`tournament-service`](./tournament-service/README.md) | `tournament-svc` | RPC + scheduler | Tournament lifecycle: CRUD, registration, brackets/standings, Challonge + Google Sheets sync, map veto, state machine; runs the outbox sweeper |
| [`parser-service`](./parser-service/README.md) | `parser-svc` | RPC + scheduler | Match-log ingestion/parsing, OverFast rank fetch (leader-locked), achievement evaluation, MVP-impact backfill |
| [`balancer-service`](./balancer-service/README.md) | `balancer-svc` | RPC worker | Genetic team balancing + live draft; heavy solve in native Rust `moo_core` (NSGA multi-objective) |
| [`analytics-service`](./analytics-service/README.md) | `analytics-svc` + `analytics-worker` | RPC worker + compute worker | Post-tournament analytics, split into two processes: `analytics-svc` (light RPC reads/mutations/job-control) and `analytics-worker` (heavy ML: LightGBM/XGBoost + Bayesian + Monte Carlo) |
| [`discord-service`](./discord-service/README.md) | `discord-worker` | Bot | discord.py bot: watches tournament channels, uploads match-log attachments to the parser over RabbitMQ, delivers notifications, FastStream consumer |
| [`shared`](./shared/README.md) | — | Library | Single-source ORM + cross-service kernel; not a running service |

All workers start with `faststream run serve:app` (analytics has both `serve_rpc:app` and `serve:app`;
discord runs `python main.py`). The only ports they expose are Prometheus `WORKER_METRICS_PORT`s —
they are **not** HTTP APIs. HTTP is served exclusively by the gateway (`:8080`).

## Requirements

* [Docker](https://www.docker.com/) and Docker Compose.
* [uv](https://docs.astral.sh/uv/) for Python package and environment management (Python 3.13+).

## General workflow

Dependencies are managed as a uv workspace. From `./backend/` install everything with:

```console
$ uv sync
```

Then activate the virtual environment:

```console
$ source .venv/bin/activate        # Linux/macOS
$ .venv\Scripts\activate           # Windows
```

Make sure your editor uses the workspace interpreter at `backend/.venv/bin/python`.

Shared SQLAlchemy models live in [`shared/models/`](./shared/README.md) (the single source of truth).
Service-specific business logic lives under each service's `src/`.

## Docker Compose (dev profiles)

Development behavior lives directly in the repository-root `docker-compose.yml`:

- source folders are bind-mounted for live reload (`--reload`),
- local PostgreSQL, Redis, and RabbitMQ are included by default,
- the gateway and nginx are part of the default stack,
- optional components (`analytics-worker`, `discord-worker`) live behind the `workers` profile.

### Start core dev stack

```console
$ docker compose up -d --wait
```

(Equivalent to `make dev-up`. The gateway and nginx come up by default — there is **no**
`--profile gateway`.)

### Start full dev stack (core + workers)

```console
$ docker compose --profile workers up -d --wait
```

(Equivalent to `make dev-up-full`.)

### Enter a running service container

```console
$ docker compose exec app-svc bash
```

### Environment files

Each service loads `backend/env/common.env` plus its own `backend/env/<service>.env`. Copy the
`*.env.example` templates to matching `.env` files before first start.

## Tests

Run the backend test suite (pytest, executed inside `app-svc`):

```console
$ make test
```

The lower-level `bash ./scripts/test.sh` still exists, but prefer `make test`. A coverage report is
generated at `htmlcov/index.html`.

## Migrations

Database schema is managed with [Alembic](https://alembic.sqlalchemy.org/); migration scripts live in
[`backend/migrations/`](./migrations) and target the shared models in [`shared/models/`](./shared/README.md).

* Apply migrations (`alembic upgrade head` inside `app-svc`):

```console
$ make migrate
```

* For interactive Alembic work, open a shell in `app-svc` (there is no `backend` compose service):

```console
$ docker compose exec app-svc bash
```

* After changing a model (for example, adding a column), create a revision:

```console
$ alembic revision --autogenerate -m "Add column last_name to User model"
```

* Commit the generated files in the `migrations/` directory, then apply with `make migrate`.
