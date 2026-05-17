from __future__ import annotations

import json
from typing import Any

from pydantic import TypeAdapter, ValidationError
from shared.schemas.realtime import (
    ClientOp,
    ErrorFrame,
    EventFrame,
    PongFrame,
    SubscribedFrame,
    WorkspaceEventEnvelope,
)

client_op_adapter = TypeAdapter(ClientOp)


class ProtocolError(Exception):
    def __init__(self, code: str, message: str, topic: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.topic = topic


def parse_client_op(raw: str) -> ClientOp:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError("invalid_json", "Frame must be valid JSON") from exc

    try:
        return client_op_adapter.validate_python(payload)
    except ValidationError as exc:
        topic = payload.get("topic") if isinstance(payload, dict) else None
        raise ProtocolError("invalid_frame", "Frame does not match realtime protocol", topic=topic) from exc


def serialize_frame(frame: ErrorFrame | EventFrame | PongFrame | SubscribedFrame) -> dict[str, Any]:
    return frame.model_dump(mode="json")


def error_frame(code: str, message: str, topic: str | None = None) -> dict[str, Any]:
    return serialize_frame(ErrorFrame(topic=topic, code=code, message=message))


def event_frame(topic: str, envelope: WorkspaceEventEnvelope) -> dict[str, Any]:
    return serialize_frame(EventFrame(topic=topic, event=envelope))


def subscribed_frame(topic: str, cursor: int) -> dict[str, Any]:
    return serialize_frame(SubscribedFrame(topic=topic, cursor=cursor))


def pong_frame() -> dict[str, Any]:
    return serialize_frame(PongFrame())
