# Analytics Service

Analytics microservice for anak-tournaments. It owns all post-tournament analytics computation.

- **Port:** 8006
- **Entry points:** `main.py` (FastAPI HTTP server), `serve.py` (FastStream RabbitMQ worker)

## Scope

- **v1 (current):** OpenSkill / Plackett-Luce shifts, linear/points algorithms, and predicted standings.
  Moved from `parser-service/src/services/analytics/` in Phase 0.
- **v2 (planned):** a classical-ML pipeline (gradient boosting + Bayesian online + Monte Carlo) for
  player performance, shifts, predicted standings, match quality, and anomaly detection.

## Entry points

- `main.py` — FastAPI HTTP server (recalculate endpoints, future read endpoints).
- `serve.py` — FastStream RabbitMQ worker (consumes `tournament_encounter_completed` and
  `analytics_recalculate` events).

## Local run

```bash
uv run uvicorn main:app --host 0.0.0.0 --port 8006
uv run faststream run serve:app
```

## Configuration & environment

See `backend/env/analytics.env`, which inherits `backend/env/common.env`.
