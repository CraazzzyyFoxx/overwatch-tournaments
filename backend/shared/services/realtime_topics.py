from __future__ import annotations

__all__ = (
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


def realtime_channel(topic: str) -> str:
    return f"{REALTIME_CHANNEL_PREFIX}{topic}"
