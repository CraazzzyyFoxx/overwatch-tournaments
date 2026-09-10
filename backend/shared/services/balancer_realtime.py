"""Event-type names for the live-balancer topic (``tournament:{id}:balancer``).

Names only. Publication goes through ``shared.services.realtime.emit``, which
is the single path for every event in the system; this module exists because
both tournament-service (registration edits) and balancer-service
(balance/config/teams edits, job lifecycle) name the same event types, and the
frontend mirrors these literals in TypeScript.

Two of them are never published from Python at all and live here so the string
has one home: ``balancer.presence`` is synthesized by the gateway from live
WebSocket connections, and ``balancer.drag`` is client-originated over the
socket's ``publish`` op (the only event type the gateway's publish allowlist
accepts).
"""

from __future__ import annotations

__all__ = (
    "BALANCER_BALANCE_SAVED",
    "BALANCER_CONFIG_CHANGED",
    "BALANCER_DRAG",
    "BALANCER_JOB_FAILED",
    "BALANCER_JOB_PROGRESS",
    "BALANCER_JOB_QUEUED",
    "BALANCER_JOB_RUNNING",
    "BALANCER_JOB_SUCCEEDED",
    "BALANCER_PRESENCE",
    "BALANCER_REGISTRATIONS_CHANGED",
    "BALANCER_TEAMS_CHANGED",
)

# Data-edit signals (persisted; clients invalidate queries).
BALANCER_REGISTRATIONS_CHANGED = "balancer.registrations_changed"
BALANCER_BALANCE_SAVED = "balancer.balance_saved"
BALANCER_TEAMS_CHANGED = "balancer.teams_changed"
BALANCER_CONFIG_CHANGED = "balancer.config_changed"

# Job lifecycle (persisted; broadcast to all viewers).
BALANCER_JOB_QUEUED = "balancer_job.queued"
BALANCER_JOB_RUNNING = "balancer_job.running"
BALANCER_JOB_PROGRESS = "balancer_job.progress"
BALANCER_JOB_SUCCEEDED = "balancer_job.succeeded"
BALANCER_JOB_FAILED = "balancer_job.failed"

# Ephemeral, gateway-synthesized from live WebSocket connections.
BALANCER_PRESENCE = "balancer.presence"

# Ephemeral live-drag overlay: client-originated over the socket and fanned out
# to co-subscribers by the gateway, never persisted.
BALANCER_DRAG = "balancer.drag"
