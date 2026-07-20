# Overwatch Tournament Platform

[![Lint Backend](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/lint-backend.yml/badge.svg)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/lint-backend.yml)
[![Test Backend](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/test-backend.yml/badge.svg)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/test-backend.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/CraazzzyyFoxx/e00b7692443a542b0e505c090cf83d35/raw/owt-coverage.json)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/test-backend.yml)
[![Issues](https://img.shields.io/github/issues/CraazzzyyFoxx/overwatch-tournaments)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/issues)
[![Documentation](https://img.shields.io/badge/documentation-yes-brightgreen.svg)](https://owt.craazzzyyfoxx.me/api/docs)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/blob/master/LICENSE)

> **OWT** provides comprehensive statistics about Overwatch Tournaments —
> the history of past tournaments and player statistics such as tournaments participated in, divisions, teams,
> heroes, and performance metrics.
> The backend is a Python microservices platform of headless [FastStream](https://faststream.airt.ai/)
> workers (SQLAlchemy, PostgreSQL, Redis, RabbitMQ) fronted by a Go gateway, and the frontend is a
> Next.js application. The project is optimized for fast and accurate data delivery while minimizing
> server load. For the full picture, see [docs/architecture.md](./docs/architecture.md).

## Table of contents

* [✨ Live instance](#-live-instance)
* [🏛️ Architecture](#-architecture)
* [🐋 Docker development](#-docker-development)
* [📈 Monitoring](#-monitoring)
* [👨‍💻 Technical details](#-technical-details)
* [🙏 Credits](#-credits)
* [📝 License](#-license)

## ✨ [Live instance](https://owt.craazzzyyfoxx.me/)

**Backend**
> The backend is a set of headless RPC workers behind a Go gateway, which is the single HTTP/WebSocket
> entry point and serves interactive API documentation (Scalar):
>
> API docs: https://owt.craazzzyyfoxx.me/api/docs

**Frontend**
> The frontend is built with Next.js and provides a user-friendly interface for interacting with the OWT API.
> It displays tournament history, player statistics, and other relevant data in an intuitive and visually appealing way.
> You can access the live frontend instance here:
>
> Frontend Live Instance: https://owt.craazzzyyfoxx.me

### Pre-commit

The project is using [pre-commit](https://pre-commit.com/) framework to ensure code quality before making any commit on the repository. After installing the project dependencies, you can install the pre-commit by using the `pre-commit install` command.

The configuration can be found in the `.pre-commit-config.yaml` file. It consists in launching 2 processes on modified files before making any commit :

- `ruff` for linting and code formatting (with `ruff format`)
- `sourcery` for more code quality checks and a lot of simplifications

## 🏛️ Architecture

**See [docs/architecture.md](./docs/architecture.md) for the full architecture** — request flow,
inter-service messaging, data model, multitenancy, and deployment topology.

OWT is a microservices monorepo. A **Go gateway** (`gateway/`) is the sole HTTP/WebSocket entry point:
it terminates HTTP behind nginx (TLS by Traefik upstream), validates JWTs, and dispatches typed
**request/reply RPC over RabbitMQ** to backend workers. The backend is a set of **headless Python
FastStream workers** (no HTTP servers) sharing one ORM layer via `backend/shared/`; they communicate
over PostgreSQL, Redis, and RabbitMQ. The frontend is a Next.js app served through the same gateway.

### Backend services (`backend/`)

| Service | Compose | Kind | Purpose | Docs |
| --- | --- | --- | --- | --- |
| `app-service` | `app-svc` | RPC worker | Core read/data API (tournaments, players, teams, heroes, maps, matches, stats) + workspace/user/metadata admin + assets + caching | [README](./backend/app-service/README.md) |
| `identity-service` | `identity-svc` | RPC worker | AuthN/AuthZ — JWT, Discord OAuth, RBAC, workspace membership, custom domains, API keys, player linking (exposed under `/api/auth`) | [README](./backend/identity-service/README.md) |
| `tournament-service` | `tournament-svc` | RPC worker + scheduler | Tournament lifecycle — CRUD, registration, brackets/standings, Challonge/Sheets sync, map veto, state machine, outbox sweeper | [README](./backend/tournament-service/README.md) |
| `parser-service` | `parser-svc` | RPC worker + scheduler | Match-log ingestion/parsing, OverFast rank fetch, achievement evaluation, MVP-impact backfill | [README](./backend/parser-service/README.md) |
| `balancer-service` | `balancer-svc` | RPC worker | Genetic team balancing (native Rust `moo_core`) + live draft | [README](./backend/balancer-service/README.md) |
| `analytics-service` | `analytics-svc` + `analytics-worker` | RPC worker + ML worker | Post-tournament analytics — OpenSkill shifts (v1), ML pipeline (v2) | [README](./backend/analytics-service/README.md) |
| `discord-service` | `discord-worker` | bot | Discord bot — match-log upload, notifications, commands | [README](./backend/discord-service/README.md) |
| `shared` | — | library | Shared ORM models, schemas, RPC/messaging, tenancy, RBAC, and utilities used by every service | [README](./backend/shared/README.md) |

The **Go gateway** (`gateway/`) is the HTTP/WebSocket edge — [README](./gateway/README.md).

### Frontend (`frontend/`)

Next.js 16 + React 19 + TypeScript, styled with Tailwind CSS 4 and Shadcn/UI, i18n via next-intl.
See [frontend/README.md](./frontend/README.md).

## 👨‍💻 Technical details

### Technology Stack and Features

- ⚡ [**FastStream**](https://faststream.airt.ai/) for the Python backend workers — headless RPC over RabbitMQ, behind a **Go** gateway (`gateway/`).
    - 🧰 [SqlAlchemy](https://www.sqlalchemy.org/) for the Python SQL database interactions (ORM).
    - 🔍 [Pydantic](https://docs.pydantic.dev) for data validation and settings management.
    - 💾 [PostgreSQL](https://www.postgresql.org) as the SQL database.
    - 🐇 [RabbitMQ](https://www.rabbitmq.com/) with [FastStream](https://faststream.airt.ai/) for inter-service messaging and workers.
    - 🧊 [Redis](https://redis.io/) for caching and realtime pub/sub.
- 🚀 [**Next.js**](https://nextjs.org/) for the frontend.
    - 💃 Using TypeScript, hooks, and other parts of a modern frontend stack.
    - 🎨 [Shadcn/UI](https://ui.shadcn.com/) for the frontend components.
- 🧪 [Vitest](https://vitest.dev) for frontend unit/smoke tests.
- 🐋 [Docker Compose](https://www.docker.com) for development and production.
- 🔭 OpenTelemetry, Prometheus, Loki, Tempo, and Grafana for observability.
- ✅ Tests with [Pytest](https://pytest.org).
- 🏭 CI/CD based on GitHub Actions.

### Computed statistics values

In statistics, various conversions are applied for ease of use:

- **Duration values** are converted to **seconds** (integer)
- **Percent values** are represented as **float**

### Redis caching

OWT API integrates a Redis-based cache system, divided into two main components:

API Cache: This high-level cache associates URIs (cache keys) with Pickle data.

Function Cache: This cache stores the results of specific functions, such as the hero statistics. The cache key is generated based on the function name and its arguments. This cache is used to store computed values that are expensive to calculate.

* Heroes: 1 day
* Maps: 1 day
* Gamemodes: 1 day
* Tournaments: 1 day
* Players: 1 hour
* Teams: 1 day
* Statistics: 1 day
* Matches: 1 day
* Achievements: 1 day

## 🐋 Docker Development

The local Docker workflow is profile-driven.

- Default dev startup (`docker compose up -d --wait`) starts core services only.
- The Go gateway + nginx edge are part of the default stack (nginx on `APP_PORT` -> gateway:8080).
- Optional profiles:
  - `workers` for background services (`docker compose --profile workers up -d --wait`)
- Local PostgreSQL is part of the dev stack by default.

### First-time setup

1. Copy root env template: `.env.example` -> `.env`
2. Copy backend env templates from `backend/env/*.env.example` to matching `.env` files
3. Start core stack:

```bash
docker compose up -d --wait
```

4. Start full stack (with background workers), if needed:

```bash
docker compose --profile workers up -d --wait
```

You can also use `make dev-up` and `make dev-up-full`.

## 📈 Monitoring

Monitoring deployment and operations are documented in [monitoring/README.md](./monitoring/README.md).

The monitoring stack runs as its own Compose project and includes Prometheus, Alertmanager, Grafana, Loki, Promtail, Tempo, the OpenTelemetry Collector, and Redis/RabbitMQ exporters.

## Backend Development

Backend docs: [backend/README.md](./backend/README.md).

## Frontend Development

Frontend docs: [frontend/README.md](./frontend/README.md).

## 🙏 Credits

All data provided by the API is owned by Anakq and their community.

- Overwatch API : [Overfast API](https://github.com/TeKrop/overfast-api)
- Anakq : [Anakq Twitch](https://www.twitch.tv/anakq)
- Special thanks for the idea and historical data [dashabreeze](https://aqt.vercel.app/players)

## 📝 License

Copyright © 2024-2025 [CraazzzyyFoxx](https://github.com/CraazzzyyFoxx).

This project is licensed under the [GNU Affero General Public License v3.0](https://github.com/CraazzzyyFoxx/overwatch-tournaments/blob/master/LICENSE) with additional attribution terms (AGPL §7). In short:

- **Self-hosting the unmodified project is allowed** — run it as-is for any purpose, including over a network.
- **Self-hosting a modified version is allowed**, but the running site must display a visible link back to this original project and its author.
- **Derivative works must stay open source** under this same license, with source code available to network users.

See the [LICENSE](./LICENSE) file for the full text and the binding Additional Terms.
