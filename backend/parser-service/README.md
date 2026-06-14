# Parser Service

Parses Overwatch match logs and runs scheduled processing for OWT. It ingests raw match data, transforms
it into the shared domain models, and triggers downstream computation.

- **Port:** 8002
- **Entry points:** `main.py` (FastAPI HTTP server), `serve.py` (FastStream worker)

## Responsibilities

- Parse and normalize match-log data into the [`shared/`](../shared/README.md) models.
- Scheduled parsing/processing jobs via [APScheduler](https://apscheduler.readthedocs.io/).
- Optimization tasks (for example, scheduling/assignment) using
  [Google OR-Tools](https://developers.google.com/optimization).
- Publish/consume events over RabbitMQ via [FastStream](https://faststream.airt.ai/) for downstream
  services (e.g. analytics recomputation).

## Running

```bash
# Development (HTTP server)
uvicorn main:app --reload --port 8002

# Worker (scheduled jobs + message consumers)
faststream run serve:app
```

## Configuration & environment

See `backend/env/parser.env`, which inherits `backend/env/common.env`. An optional outbound proxy can be
configured (`PROXY_HOST` / `PROXY_PORT`) for fetching external data.
