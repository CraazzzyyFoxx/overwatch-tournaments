from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import WebSocket
from shared.models.auth_user import AuthUser


@dataclass(eq=False)
class ConnectionState:
    websocket: WebSocket
    user: AuthUser | None
    topics: set[str] = field(default_factory=set)


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

    async def route(self, topic: str, frame: dict) -> None:
        for state in list(self._states):
            if topic not in state.topics:
                continue
            try:
                await state.websocket.send_json(frame)
            except Exception:
                self.cleanup(state)

    def cleanup(self, state: ConnectionState) -> None:
        state.topics.clear()
        self._states.discard(state)


connection_manager = ConnectionManager()
