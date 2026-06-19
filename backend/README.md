# Backend

The OWT backend is a Python microservices monorepo. Each service is an independent FastAPI
application with its own `pyproject.toml`, while all services share one ORM/schema layer through
[`shared/`](./shared/README.md). Dependencies are managed as a single [uv](https://docs.astral.sh/uv/)
workspace rooted at this directory.

## Services

| Service | Port | Purpose |
| --- | --- | --- |
| [`app-service`](./app-service/README.md) | 8000 | Core public REST API + Redis caching |
| [`auth-service`](./auth-service/README.md) | 8001 | Authentication, JWT, Discord OAuth, player linking |
| [`parser-service`](./parser-service/README.md) | 8002 | Match-log parsing & scheduled processing |
| [`balancer-service`](./balancer-service/README.md) | 8003 | Genetic-algorithm team balancing |
| [`tournament-service`](./tournament-service/README.md) | 8004 | Tournament domain API + workers |
| [`realtime-service`](./realtime-service/README.md) | — | Decommissioned: WebSockets served by the Go `gateway/` (code kept for reference) |
| [`analytics-service`](./analytics-service/README.md) | 8006 | OpenSkill / ML analytics |
| [`discord-service`](./discord-service/README.md) | — | Discord bot integration |
| [`twitch-service`](./twitch-service/README.md) | — | Twitch integration (inactive) |
| [`shared`](./shared/README.md) | — | Shared ORM models, schemas, clients, utilities |

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
Service-specific API endpoints and business logic live under each service's `src/`.

## Docker Compose (dev profiles)

`docker-compose.override.yml` is no longer used. Development behavior lives directly in the
repository-root `docker-compose.yml`:

- source folders are bind-mounted for live reload,
- backend services run with `uvicorn --reload`,
- local PostgreSQL, Redis, and RabbitMQ are included by default,
- optional components use Compose profiles.

### Start core dev stack

```console
$ docker compose up -d --wait
```

### Start full dev stack (gateway + workers)

```console
$ docker compose --profile gateway --profile workers up -d --wait
```

(Equivalent `make dev-up` / `make dev-up-full` targets are available.)

### Enter a running service container

```console
$ docker compose exec <service> bash
```

### Environment files

Each service loads `backend/env/common.env` plus its own `backend/env/<service>.env`. Copy the
`*.env.example` templates to matching `.env` files before first start.

## Tests

Run the backend test suite:

```console
$ bash ./scripts/test.sh
```

Tests run with Pytest. When the tests run, an `htmlcov/index.html` coverage report is generated.

## Migrations

Database schema is managed with [Alembic](https://alembic.sqlalchemy.org/); migration scripts live in
[`backend/migrations/`](./migrations) and target the shared models in [`shared/models/`](./shared/README.md).
Because the source directory is mounted into the container during local development, you can run Alembic
inside the container and the generated files appear in your working tree.

* Start an interactive session in a backend container:

```console
$ docker compose exec backend bash
```

* After changing a model (for example, adding a column), create a revision:

```console
$ alembic revision --autogenerate -m "Add column last_name to User model"
```

* Commit the generated files in the `migrations/` directory.

* Apply the migration to the database:

```console
$ alembic upgrade head
```
