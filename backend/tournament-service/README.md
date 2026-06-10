# Tournament Service

The tournament domain API and its background workers — the heart of OWT's tournament lifecycle, from
registration through bracket generation, results, and realtime updates.

- **Port:** 8004
- **Entry points:** `main.py` (FastAPI HTTP server), `serve.py` (FastStream workers, outbox sweeper, scheduler)

## Responsibilities

- **Health**: `/health/live`, `/health/ready`
- **Public read**: routes under `/tournaments`, `/encounters`, and `/teams`
- **Registration**: public registration routes under
  `/workspaces/{workspace_id}/tournaments/{tournament_id}/registration`
- **Captain results**: result routes under `/encounters/{id}/...`
- **Admin**: tournament / stage / team / player / encounter / standing routes under `/admin`
- **Challonge integration**: read / import / export / push / log routes under `/admin/challonge`
- **Balancer & sheets**: admin registration, status catalog, Google Sheets sync / preview / suggest, and
  active-registration export under `/admin/balancer` and `/admin/ws`
- **Map veto**: routes and a websocket under `/encounters/{id}/map-pool`

## Realtime & messaging

- Tournament realtime events are published to `realtime.workspace_event` for `realtime-service` fan-out.
- A RabbitMQ `tournament_changed` consumer handles cache invalidation.
- Redis realtime publish enables multi-replica WebSocket broadcast through `realtime-service`.
- A transactional outbox publishes captain/admin tournament changes, recalculations, encounter
  completion, registration approvals/rejections, and tournament state changes; the outbox sweeper runs in
  `serve.py`.

## Background jobs

- Durable computation jobs with a history/status API under `/admin/tournament-jobs`.
- Bracket worker consuming `tournament_bracket_jobs`.
- Standings worker consuming `tournament_standings_jobs`.
- Worker scheduler for registration Google Sheets sync.

## Running

```bash
# Development (HTTP server)
uvicorn main:app --reload --port 8004

# Workers (outbox sweeper, bracket/standings consumers, scheduler)
faststream run serve:app
```

## Configuration & environment

See `backend/env/tournament.env`, which inherits `backend/env/common.env`.
