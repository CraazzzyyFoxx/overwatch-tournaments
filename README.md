# Overwatch Tournament Platform

[![Lint Backend](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/lint-backend.yml/badge.svg)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/lint-backend.yml)
[![Test Backend](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/test-backend.yml/badge.svg)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/test-backend.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://gist.githubusercontent.com/CraazzzyyFoxx/e00b7692443a542b0e505c090cf83d35/raw/owt-coverage.json)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/actions/workflows/test-backend.yml)
[![Issues](https://img.shields.io/github/issues/CraazzzyyFoxx/overwatch-tournaments)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/issues)
[![Documentation](https://img.shields.io/badge/documentation-yes-brightgreen.svg)](https://anakq.xyz/api/redoc)
[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://github.com/CraazzzyyFoxx/overwatch-tournaments/blob/master/LICENSE)

> **OWT** provides comprehensive statistics about Overwatch Tournaments —
> the history of past tournaments and player statistics such as tournaments participated in, divisions, teams,
> heroes, and performance metrics.
> The backend is a Python microservices platform (FastAPI, SQLAlchemy, PostgreSQL, Redis, RabbitMQ) and the
> frontend is a Next.js application. The project is optimized for fast and accurate data delivery while
> minimizing server load.

## Table of contents

* [✨ Live instance](#-live-instance)
* [🏛️ Architecture](#-architecture)
* [🐋 Docker development](#docker-development-breaking-change)
* [📈 Monitoring](#-monitoring)
* [👨‍💻 Technical details](#-technical-details)
* [🙏 Credits](#-credits)
* [📝 License](#-license)

## ✨ [Live instance](https://anakq.xyz/)

**Backend**
> The backend is built with FastAPI and provides the core API functionality, including data retrieval, caching, and processing.
> You can explore the backend API documentation using the following links:
>
> Redoc Documentation: https://anakq.xyz/api/v1/redoc
> Swagger UI: https://anakq.xyz/api/v1/docs

**Frontend**
> The frontend is built with Next.js and provides a user-friendly interface for interacting with the OWT API.
> It displays tournament history, player statistics, and other relevant data in an intuitive and visually appealing way.
> You can access the live frontend instance here:
>
> Frontend Live Instance: https://anakq.xyz

### Pre-commit

The project is using [pre-commit](https://pre-commit.com/) framework to ensure code quality before making any commit on the repository. After installing the project dependencies, you can install the pre-commit by using the `pre-commit install` command.

The configuration can be found in the `.pre-commit-config.yaml` file. It consists in launching 2 processes on modified files before making any commit :

- `ruff` for linting and code formatting (with `ruff format`)
- `sourcery` for more code quality checks and a lot of simplifications

## 🏛️ Architecture

OWT is a microservices monorepo: a set of independent Python services under `backend/` (sharing one ORM layer
via `backend/shared/`) plus a Next.js frontend. In production the services sit behind nginx and a Go gateway
(`gateway/`) and communicate over PostgreSQL, Redis, and RabbitMQ.

### Backend services (`backend/`)

| Service | Port | Purpose | Docs |
| --- | --- | --- | --- |
| `app-service` | 8000 | Core public REST API — data retrieval, Redis caching, statistics endpoints | [README](./backend/app-service/README.md) |
| `auth-service` | 8001 | Authentication & authorization — JWT, Discord OAuth, player linking | [README](./backend/auth-service/README.md) |
| `parser-service` | 8002 | Match-log parsing & scheduled processing (OR-Tools, APScheduler, FastStream) | [README](./backend/parser-service/README.md) |
| `balancer-service` | 8003 | Genetic-algorithm team balancing (async jobs + SSE) | [README](./backend/balancer-service/README.md) |
| `tournament-service` | 8004 | Tournament domain — CRUD, registration, Challonge/Sheets sync, map veto, realtime | [README](./backend/tournament-service/README.md) |
| `realtime-service` | 8005 | Unified WebSocket gateway with Redis pub/sub fan-out | [README](./backend/realtime-service/README.md) |
| `analytics-service` | 8006 | Post-tournament analytics — OpenSkill (v1), ML pipeline (v2) | [README](./backend/analytics-service/README.md) |
| `discord-service` | — | Discord bot integration and notifications | [README](./backend/discord-service/README.md) |
| `twitch-service` | — | Twitch integration (inactive placeholder) | [README](./backend/twitch-service/README.md) |
| `shared` | — | Shared ORM models, schemas, clients, and utilities used by every service | [README](./backend/shared/README.md) |

### Frontend (`frontend/`)

Next.js 16 + React 19 + TypeScript, styled with Tailwind CSS 4 and Shadcn/UI. See [frontend/README.md](./frontend/README.md).

## 👨‍💻 Technical details

### Technology Stack and Features

- ⚡ [**FastAPI**](https://fastapi.tiangolo.com) for the Python backend services.
    - 🧰 [SqlAlchemy](https://www.sqlalchemy.org/) for the Python SQL database interactions (ORM).
    - 🔍 [Pydantic](https://docs.pydantic.dev), used by FastAPI, for the data validation and settings management.
    - 💾 [PostgreSQL](https://www.postgresql.org) as the SQL database.
    - 🐇 [RabbitMQ](https://www.rabbitmq.com/) with [FastStream](https://faststream.airt.ai/) for inter-service messaging and workers.
    - 🧊 [Redis](https://redis.io/) for caching and realtime pub/sub.
- 🚀 [**Next.js**](https://nextjs.org/) for the frontend.
    - 💃 Using TypeScript, hooks, and other parts of a modern frontend stack.
    - 🎨 [Shadcn/UI](https://ui.shadcn.com/) for the frontend components.
    - 🧪 [Playwright](https://playwright.dev) for End-to-End testing.
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

## Docker Development (Breaking Change)

The local Docker workflow has changed and is now profile-driven.

- `docker-compose.override.yml` has been removed.
- Default dev startup (`docker compose up -d --wait`) now starts core services only.
- The Go gateway + nginx edge are part of the default stack (nginx on `APP_PORT` -> gateway:8080).
- Optional profiles:
  - `workers` for background services (`docker compose --profile workers up -d --wait`)
- Local PostgreSQL is now part of the dev stack by default.

### First-time setup

1. Copy root env template: `.env.example` -> `.env`
2. Copy backend env templates from `backend/env/*.env.example` to matching `.env` files
3. Start core stack:

```bash
docker compose up -d --wait
```

4. Start full stack (gateway + workers), if needed:

```bash
docker compose --profile gateway --profile workers up -d --wait
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
