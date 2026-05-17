from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

__all__ = (
    "ErrorFrame",
    "EventFrame",
    "PingOp",
    "PongFrame",
    "SubscribeOp",
    "SubscribedFrame",
    "TopicPattern",
    "UnsubscribeOp",
    "WorkspaceEventEnvelope",
)


class TopicPattern:
    """Segment matcher for realtime topics.

    ``*`` matches exactly one segment. Topic shapes intentionally stay simple:
    ``tournament:<id>:bracket`` or ``workspace:<id>:notifications``.
    """

    def __init__(self, pattern: str) -> None:
        self.pattern = pattern
        self._segments = pattern.split(":")

    def match(self, topic: str) -> tuple[str, ...] | None:
        topic_segments = topic.split(":")
        if len(topic_segments) != len(self._segments):
            return None

        groups: list[str] = []
        for expected, actual in zip(self._segments, topic_segments, strict=True):
            if expected == "*":
                groups.append(actual)
                continue
            if expected != actual:
                return None
        return tuple(groups)


class WorkspaceEventEnvelope(BaseModel):
    event_id: int
    event_type: str
    schema_version: int = 1
    occurred_at: datetime
    actor_user_id: int | None = None
    data: dict[str, Any]


class SubscribeOp(BaseModel):
    op: Literal["subscribe"]
    topic: str = Field(min_length=1, max_length=255)
    after_event_id: int | None = Field(default=None, ge=0)


class UnsubscribeOp(BaseModel):
    op: Literal["unsubscribe"]
    topic: str = Field(min_length=1, max_length=255)


class PingOp(BaseModel):
    op: Literal["ping"]


ClientOp = Annotated[SubscribeOp | UnsubscribeOp | PingOp, Field(discriminator="op")]


class SubscribedFrame(BaseModel):
    op: Literal["subscribed"] = "subscribed"
    topic: str
    cursor: int


class ErrorFrame(BaseModel):
    op: Literal["error"] = "error"
    topic: str | None = None
    code: str
    message: str


class EventFrame(BaseModel):
    op: Literal["event"] = "event"
    topic: str
    event: WorkspaceEventEnvelope


class PongFrame(BaseModel):
    op: Literal["pong"] = "pong"
