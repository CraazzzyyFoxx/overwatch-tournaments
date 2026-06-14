from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from fastapi import WebSocket


class MapVetoConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, encounter_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[encounter_id].add(websocket)

    def disconnect(self, encounter_id: int, websocket: WebSocket) -> None:
        connection_group = self._connections.get(encounter_id)
        if connection_group is None:
            return

        connection_group.discard(websocket)
        if not connection_group:
            self._connections.pop(encounter_id, None)

    async def send_state(self, websocket: WebSocket, state: dict[str, Any]) -> None:
        await websocket.send_json({"type": "veto.state", "data": state})

    async def send_error(
        self,
        websocket: WebSocket,
        *,
        code: str,
        message: str,
    ) -> None:
        await websocket.send_json(
            {
                "type": "veto.error",
                "error": {
                    "code": code,
                    "message": message,
                },
            }
        )

    async def broadcast_state(self, encounter_id: int, state_by_socket: dict[WebSocket, dict[str, Any]]) -> None:
        for websocket, state in state_by_socket.items():
            if websocket not in self._connections.get(encounter_id, set()):
                continue
            try:
                await self.send_state(websocket, state)
            except Exception:
                self.disconnect(encounter_id, websocket)

    def get_connections(self, encounter_id: int) -> Iterable[WebSocket]:
        return tuple(self._connections.get(encounter_id, set()))


manager = MapVetoConnectionManager()
