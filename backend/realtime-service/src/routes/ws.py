from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from shared.services.realtime_publisher import event_to_envelope
from sqlalchemy.ext.asyncio import AsyncSession

from src.core import config, db
from src.core.auth import get_websocket_user_optional
from src.protocol import (
    ProtocolError,
    error_frame,
    event_frame,
    parse_client_op,
    pong_frame,
    subscribed_frame,
)
from src.services.connection_manager import connection_manager
from src.services.event_replay import ReplayGapTooLarge, event_replay_service
from src.services.topic_acl import topic_acl_registry

router = APIRouter()


@router.websocket("/ws")
async def ws_endpoint(
    websocket: WebSocket,
    session: AsyncSession = Depends(db.get_async_session),
) -> None:
    user = await get_websocket_user_optional(websocket, session)
    state = await connection_manager.register(websocket, user)
    try:
        while True:
            try:
                raw_frame = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=config.settings.ws_idle_timeout,
                )
            except TimeoutError:
                await websocket.close(code=1001)
                return

            try:
                op = parse_client_op(raw_frame)
            except ProtocolError as exc:
                await websocket.send_json(error_frame(exc.code, exc.message, topic=exc.topic))
                continue

            if op.op == "ping":
                await websocket.send_json(pong_frame())
                continue

            if op.op == "unsubscribe":
                connection_manager.unsubscribe(state, op.topic)
                continue

            if not await topic_acl_registry.allow(user, op.topic, session):
                await websocket.send_json(
                    error_frame(
                        "forbidden",
                        "You are not allowed to subscribe to this topic",
                        topic=op.topic,
                    )
                )
                continue

            cursor = await event_replay_service.current_cursor(session, op.topic)
            await connection_manager.subscribe(state, op.topic)
            try:
                events = await event_replay_service.since(
                    session,
                    topic=op.topic,
                    after_event_id=op.after_event_id,
                    up_to_event_id=cursor,
                )
            except ReplayGapTooLarge:
                connection_manager.unsubscribe(state, op.topic)
                await websocket.send_json(
                    error_frame(
                        "replay_gap_too_large",
                        "Too many missed events; refetch a fresh snapshot before subscribing again",
                        topic=op.topic,
                    )
                )
                continue

            for event in events:
                await websocket.send_json(event_frame(op.topic, event_to_envelope(event)))
            await websocket.send_json(subscribed_frame(op.topic, cursor))
    except WebSocketDisconnect:
        return
    finally:
        connection_manager.cleanup(state)
