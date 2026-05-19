from __future__ import annotations

__all__ = (
    "analytics_jobs",
    "bracket",
    "draft",
    "realtime_channel",
    "workspace_notifications",
)

REALTIME_CHANNEL_PREFIX = "realtime:"


def bracket(tournament_id: int) -> str:
    return f"tournament:{int(tournament_id)}:bracket"


def draft(tournament_id: int) -> str:
    return f"tournament:{int(tournament_id)}:draft"


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
