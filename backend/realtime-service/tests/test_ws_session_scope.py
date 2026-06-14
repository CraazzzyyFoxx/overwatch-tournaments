from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "realtime-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

ws = importlib.import_module("src.routes.ws")
connection_manager = importlib.import_module("src.services.connection_manager")


class _SessionContext:
    def __init__(self) -> None:
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc_info):
        self.closed = True


class _SessionMaker:
    def __init__(self) -> None:
        self.context = _SessionContext()

    def __call__(self) -> _SessionContext:
        return self.context


class _AllowingAcl:
    async def allow(self, *_args, **_kwargs) -> bool:
        return True


class _DenyingAcl:
    async def allow(self, *_args, **_kwargs) -> bool:
        return False


class _ReplayService:
    async def current_cursor(self, _session, _topic: str) -> int:
        return 42

    async def since(self, *_args, **_kwargs) -> list:
        return []


class _ExplodingReplayService:
    async def current_cursor(self, *_args, **_kwargs) -> int:
        raise AssertionError("replay must not run when ACL denies the topic")


class _RecordingManager:
    def __init__(self, session_context: _SessionContext) -> None:
        self.session_context = session_context
        self.sent: list[dict] = []
        self.subscribed_topics: list[str] = []

    async def subscribe(self, _state, topic: str) -> int:
        assert self.session_context.closed
        self.subscribed_topics.append(topic)
        return 0

    def unsubscribe(self, _state, _topic: str) -> None:
        assert self.session_context.closed

    async def send(self, _state, frame: dict) -> bool:
        assert self.session_context.closed
        self.sent.append(frame)
        return True


class _WebSocket:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.accepted = False
        self.sent: list[dict] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, frame: dict) -> None:
        if self.fail:
            raise RuntimeError("closed")
        self.sent.append(frame)


class WebSocketSessionScopeTests(IsolatedAsyncioTestCase):
    async def test_subscribe_closes_db_session_before_websocket_sends(self) -> None:
        session_maker = _SessionMaker()
        manager = _RecordingManager(session_maker.context)
        op = ws.SubscribeOp(op="subscribe", topic="tournament:72:draft", after_event_id=3)

        with (
            patch.object(ws.db, "async_session_maker", session_maker),
            patch.object(ws, "topic_acl_registry", _AllowingAcl()),
            patch.object(ws, "event_replay_service", _ReplayService()),
            patch.object(ws, "connection_manager", manager),
        ):
            await ws._handle_subscribe(object(), op, None)

        self.assertEqual(manager.subscribed_topics, ["tournament:72:draft"])
        self.assertEqual(manager.sent[-1], {"op": "subscribed", "topic": "tournament:72:draft", "cursor": 42})

    async def test_forbidden_subscribe_sends_error_after_closing_db_session(self) -> None:
        session_maker = _SessionMaker()
        manager = _RecordingManager(session_maker.context)
        op = ws.SubscribeOp(op="subscribe", topic="workspace:6:private", after_event_id=None)

        with (
            patch.object(ws.db, "async_session_maker", session_maker),
            patch.object(ws, "topic_acl_registry", _DenyingAcl()),
            patch.object(ws, "event_replay_service", _ExplodingReplayService()),
            patch.object(ws, "connection_manager", manager),
        ):
            await ws._handle_subscribe(object(), op, None)

        self.assertEqual(manager.sent[0]["op"], "error")
        self.assertEqual(manager.sent[0]["code"], "forbidden")


class ConnectionManagerFanoutTests(IsolatedAsyncioTestCase):
    async def test_route_keeps_fast_clients_and_cleans_failed_clients(self) -> None:
        manager = connection_manager.ConnectionManager()
        fast = await manager.register(_WebSocket(), None)
        failed = await manager.register(_WebSocket(fail=True), None)
        await manager.subscribe(fast, "tournament:72:draft")
        await manager.subscribe(failed, "tournament:72:draft")

        frame = {
            "op": "event",
            "topic": "tournament:72:draft",
            "event": {
                "event_id": 10,
                "occurred_at": "2026-06-05T12:00:00+00:00",
            },
        }

        await manager.route("tournament:72:draft", frame)

        self.assertEqual(fast.websocket.sent, [frame])
        self.assertIn(fast, manager._states)
        self.assertNotIn(failed, manager._states)
