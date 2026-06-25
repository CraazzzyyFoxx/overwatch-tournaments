from __future__ import annotations

__all__ = (
    "analytics_jobs",
    "balancer",
    "bracket",
    "draft",
    "logs",
    "map_veto",
    "realtime_channel",
    "workspace_notifications",
)

REALTIME_CHANNEL_PREFIX = "realtime:"


def bracket(tournament_id: int) -> str:
    return f"tournament:{int(tournament_id)}:bracket"


def draft(tournament_id: int) -> str:
    return f"tournament:{int(tournament_id)}:draft"


def map_veto(encounter_id: int) -> str:
    """Public topic for live map-veto/pick updates on a single encounter.

    Carries a thin ``map_veto.updated`` signal (no per-viewer state); clients
    refetch the map-pool state on receipt. Public-subscribable, like the
    bracket/draft spectator topics.
    """
    return f"encounter:{int(encounter_id)}:map-veto"


def balancer(tournament_id: int) -> str:
    """Topic for live balancer collaboration on a single tournament.

    Carries data-edit signals (``balancer.*_changed``), job-status events
    (``balancer_job.*``), and ephemeral presence (``balancer.presence``).
    Unlike the public draft/bracket topics, access is gated by workspace
    membership (see the gateway topic ACL, gateway/internal/acl).
    """
    return f"tournament:{int(tournament_id)}:balancer"


def logs(workspace_id: int) -> str:
    """Topic for live match-log processing updates within a workspace.

    Carries a thin ``logs.updated`` signal (no record data); the admin log
    monitor refetches ``/admin/logs/history`` on receipt. Gated by workspace
    membership via the existing ``workspace:*:*`` ACL rule.
    """
    return f"workspace:{int(workspace_id)}:logs"


def workspace_notifications(workspace_id: int) -> str:
    return f"workspace:{int(workspace_id)}:notifications"


def analytics_jobs(workspace_id: int) -> str:
    """Topic for unified analytics-job progress events.

    Frontend subscribes to ``workspace:{id}:analytics_jobs`` after a job is
    dispatched and receives ``analytics_job.*`` events as the worker runs
    each stage.
    """
    return f"workspace:{int(workspace_id)}:analytics_jobs"


def realtime_channel(topic: str) -> str:
    return f"{REALTIME_CHANNEL_PREFIX}{topic}"
