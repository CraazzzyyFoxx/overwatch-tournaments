# Realtime Service

> **Decommissioned.** WebSockets are now served by the Go `gateway/` (`gateway/internal/ws`),
> a behavior-preserving port of this service: same protocol, topic ACL, cursor replay from
> `realtime.workspace_event`, presence, and `realtime:*` Redis fan-in. This service is no longer
> built or deployed (removed from docker-compose dev/prod and the Kong `/api/realtime` route now
> targets `gateway:8080`). The code is kept here for reference and may be deleted later.

The unified WebSocket gateway for OWT. It holds client WebSocket connections and fans out realtime events
(tournament/registration/encounter updates) published by other services, enabling multi-replica broadcast.

- **Port:** 8005
- **Entry point:** `main.py` (FastAPI HTTP + WebSocket server)

## Responsibilities

- Accept and manage client WebSocket connections for live updates.
- Subscribe to Redis pub/sub channels and forward events to connected clients, so broadcasts work across
  multiple replicas.
- Consume workspace events (e.g. `realtime.workspace_event` published by `tournament-service`) and route
  them to the right clients.

## Running

```bash
# Development
uvicorn main:app --reload --port 8005

# Production
uvicorn main:app --host 0.0.0.0 --port 8005
```

Health: `GET /health/live`, `GET /health/ready`.

## Configuration & environment

See `backend/env/realtime.env`, which inherits `backend/env/common.env`. Requires Redis connectivity for
pub/sub fan-out.
