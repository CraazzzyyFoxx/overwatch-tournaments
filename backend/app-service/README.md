# App Service

The core public REST API for OWT — the primary application server that serves tournament, player, team,
hero, map, match, and statistics data to the frontend and external API consumers.

- **Port:** 8000
- **Entry point:** `main.py` (FastAPI HTTP server)

## Responsibilities

- Public, read-optimized API endpoints for the data shown on the site (tournaments, players, teams,
  heroes, maps, matches, achievements, statistics).
- Redis-based caching to keep responses fast and minimize database load (see the caching section in the
  repository [root README](../../README.md)).
- Serves the OpenAPI documentation (Redoc / Swagger).

## API documentation

- Redoc: `http://localhost:8000/api/v1/redoc`
- Swagger UI: `http://localhost:8000/api/v1/docs`

## Running

```bash
# Development
uvicorn main:app --reload --port 8000

# Production
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Configuration & environment

See `backend/env/app.env`, which inherits `backend/env/common.env`. Shared ORM models come from
[`shared/`](../shared/README.md).
