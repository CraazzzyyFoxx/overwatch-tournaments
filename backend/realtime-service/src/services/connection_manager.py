from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from fastapi import WebSocket
from loguru import logger
from shared.models.auth_user import AuthUser

SEND_TIMEOUT_SECONDS = 2.0


@dataclass(eq=False)
class ConnectionState:
    websocket: WebSocket
    user: AuthUser | None
    topics: set[str] = field(default_factory=set)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class ConnectionManager:
    def __init__(self) -> None:
        self._states: set[ConnectionState] = set()

    async def register(self, websocket: WebSocket, user: AuthUser | None) -> ConnectionState:
        await websocket.accept()
        state = ConnectionState(websocket=websocket, user=user)
        self._states.add(state)
        return state

    async def subscribe(self, state: ConnectionState, topic: str) -> int:
        state.topics.add(topic)
        return 0

    def unsubscribe(self, state: ConnectionState, topic: str) -> None:
        state.topics.discard(topic)

    async def send(self, state: ConnectionState, frame: dict[str, Any]) -> bool:
        try:
            async with state.send_lock:
                await asyncio.wait_for(
                    state.websocket.send_json(frame),
                    timeout=SEND_TIMEOUT_SECONDS,
                )
        except Exception:
            self.cleanup(state)
            return False
        return True

    async def route(self, topic: str, frame: dict[str, Any]) -> None:
        states = [state for state in list(self._states) if topic in state.topics]
        if not states:
            return

        started = perf_counter()
        results = await asyncio.gather(
            *(self.send(state, frame) for state in states),
            return_exceptions=False,
        )
        delivered = sum(1 for delivered_one in results if delivered_one)
        logger.debug(
            "Routed realtime event",
            topic=topic,
            subscribers=len(states),
            delivered=delivered,
            event_id=_event_id(frame),
            delivery_latency_ms=_delivery_latency_ms(frame),
            fanout_ms=round((perf_counter() - started) * 1000, 2),
        )

    def cleanup(self, state: ConnectionState) -> None:
        state.topics.clear()
        self._states.discard(state)


connection_manager = ConnectionManager()


def _event_id(frame: dict[str, Any]) -> int | None:
    event = frame.get("event")
    if not isinstance(event, dict):
        return None
    event_id = event.get("event_id")
    return event_id if isinstance(event_id, int) else None


def _delivery_latency_ms(frame: dict[str, Any]) -> int | None:
    event = frame.get("event")
    if not isinstance(event, dict):
        return None
    occurred_at = event.get("occurred_at")
    if not isinstance(occurred_at, str):
        return None
    try:
        occurred = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    return max(0, int((datetime.now(UTC) - occurred.astimezone(UTC)).total_seconds() * 1000))
