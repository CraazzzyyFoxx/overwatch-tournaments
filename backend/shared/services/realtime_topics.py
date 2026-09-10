"""The Redis channel namespace for realtime frames.

Topic STRINGS are built by ``shared.services.realtime.Scope`` — that is the one
place their format lives. What remains here is the channel prefix the gateway's
``PSUBSCRIBE realtime:*`` binds to (``gateway/internal/events/events.go``), kept
separate because it is a transport detail rather than part of any topic.

The per-domain builders (``bracket()``, ``draft()``, ``user_notifications()``,
...) are gone: a scope now answers both ``invalidation_topic`` and
``domain_topic(domain)``, so the format cannot drift between a publisher, the
retention job's LIKE pattern and the gateway's prefix split the way it used to.
"""

from __future__ import annotations

__all__ = ("REALTIME_CHANNEL_PREFIX", "realtime_channel")

REALTIME_CHANNEL_PREFIX = "realtime:"


def realtime_channel(topic: str) -> str:
    return f"{REALTIME_CHANNEL_PREFIX}{topic}"
