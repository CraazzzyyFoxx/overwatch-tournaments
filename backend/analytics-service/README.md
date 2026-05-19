# analytics-service

Analytics microservice for anak-tournaments.

Owns all post-tournament analytics computation:

- v1 (current): OpenSkill/Plackett-Luce shifts, linear/points algorithms, predicted standings.
  Moved from `parser-service/src/services/analytics/` in Phase 0.
- v2 (planned): classical-ML pipeline (gradient boosting + Bayesian online + Monte Carlo) for
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

## Environment

See `backend/env/analytics.env`. Inherits `backend/env/common.env`.
