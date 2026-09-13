"""``rpc.stream.health`` — the read the admin panel is built on.

Two properties, both easy to lose quietly:

1. **A workspace-scoped grant is not enough.** There is one poller for the whole
   platform and one Redis key, so the numbers carry no workspace dimension. A
   workspace admin holding ``stream.read`` in their own workspace must NOT be able
   to read platform-wide poller state, and the handler therefore checks a *global*
   permission rather than calling ``ensure_workspace_permission``. Swap it for the
   workspace gate and every workspace admin starts reading cross-tenant operational
   data — with no test failing anywhere else.

2. **"Never ran" is not "failed".** The panel renders those two differently, so a
   missing status must stay ``None`` on the wire instead of collapsing into a
   default like ``"error"`` or ``"empty"``.

Runs under stdlib unittest with a fake session and a fake Redis: no database, no
broker, and the real ``AuthUser`` rehydration so the permission decisions are the
production ones.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "stream-service"))


from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.rpc.identity import MissingIdentityError  # noqa: E402
from shared.schemas.settings import StreamCollectionConfig  # noqa: E402
from src.rpc import admin  # noqa: E402
from src.services import state  # noqa: E402

WORKSPACE = 7

#: Holds stream.read globally — a platform operator.
GLOBAL_READER: dict[str, Any] = {
    "user_id": 1,
    "username": "operator",
    "is_superuser": False,
    "is_active": True,
    "roles": [],
    "permissions": [{"resource": "stream", "action": "read"}],
    "workspaces": [],
}

#: Holds stream.read inside ONE workspace. Must not reach platform-wide state:
#: a workspace-scoped grant cannot widen itself by dropping a query param.
WORKSPACE_READER: dict[str, Any] = {
    "user_id": 2,
    "username": "ws-admin",
    "is_superuser": False,
    "is_active": True,
    "roles": [],
    "permissions": [],
    "workspaces": [
        {
            "workspace_id": WORKSPACE,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "stream", "action": "read"}],
        }
    ],
}

SUPERUSER: dict[str, Any] = {
    "user_id": 3,
    "username": "root",
    "is_superuser": True,
    "is_active": True,
    "roles": [],
    "permissions": [],
    "workspaces": [],
}


def _request(identity: dict[str, Any] | None) -> dict[str, Any]:
    data: dict[str, Any] = {"query": {}}
    if identity is not None:
        data["identity"] = identity
    return data


class _FakeRedis:
    def __init__(self, status: dict[str, Any] | None = None) -> None:
        self.strings: dict[str, str] = {}
        if status is not None:
            self.strings[state.POLL_STATUS_KEY] = json.dumps(status)

    async def get(self, key: str) -> str | None:
        return self.strings.get(key)


class _HealthCase(IsolatedAsyncioTestCase):
    cfg = StreamCollectionConfig(enabled=True, interval_seconds=90, batch_size=50)

    def _wire(self, *, status: dict[str, Any] | None, configured: bool = True) -> None:
        redis_patcher = patch.object(admin, "realtime_redis", _FakeRedis(status))
        redis_patcher.start()
        self.addCleanup(redis_patcher.stop)

        async def _cfg(_session: Any) -> StreamCollectionConfig:
            return self.cfg

        cfg_patcher = patch.object(admin, "get_stream_collection_config", _cfg)
        cfg_patcher.start()
        self.addCleanup(cfg_patcher.stop)

        creds_patcher = patch.multiple(
            admin.settings,
            twitch_client_id="cid" if configured else None,
            twitch_client_secret="secret" if configured else None,
        )
        creds_patcher.start()
        self.addCleanup(creds_patcher.stop)


class PermissionTests(_HealthCase):
    async def test_global_reader_is_allowed(self) -> None:
        self._wire(status=None)

        result = await admin.health(object(), _request(GLOBAL_READER))

        self.assertEqual(result.interval_seconds, 90)

    async def test_superuser_is_allowed(self) -> None:
        self._wire(status=None)

        result = await admin.health(object(), _request(SUPERUSER))

        self.assertTrue(result.enabled)

    async def test_workspace_scoped_grant_cannot_read_platform_state(self) -> None:
        """The whole reason the handler does not call ensure_workspace_permission."""
        self._wire(status=None)

        with self.assertRaises(HTTPException) as caught:
            await admin.health(object(), _request(WORKSPACE_READER))

        self.assertEqual(caught.exception.status_code, 403)

    async def test_anonymous_is_rejected(self) -> None:
        """Raised as ``MissingIdentityError``, which ``_common.envelope`` maps to
        the ``unauthorized`` code — a 401, not the 403 a wrong-permission call gets.
        Asserting the raw exception keeps that distinction visible here."""
        self._wire(status=None)

        with self.assertRaises(MissingIdentityError):
            await admin.health(object(), _request(None))


class PayloadTests(_HealthCase):
    async def test_no_recorded_tick_reports_null_status_not_a_failure(self) -> None:
        self._wire(status=None)

        result = await admin.health(object(), _request(GLOBAL_READER))

        self.assertIsNone(result.status)
        self.assertIsNone(result.last_run_at)
        self.assertIsNone(result.live_channels)
        # The config still answers, so the panel can say "paused"/"every 90s".
        self.assertEqual(result.batch_size, 50)

    async def test_recorded_tick_is_reported_verbatim(self) -> None:
        self._wire(
            status={
                "ran_at": 1_755_300_000.0,
                "status": "unauthorized",
                "tournaments_active": 3,
                "tournaments_updated": 0,
                "channels_polled": 12,
                "live_channels": 0,
                "ratelimit_remaining": 640,
            }
        )

        result = await admin.health(object(), _request(GLOBAL_READER))

        self.assertEqual(result.status, "unauthorized")
        self.assertEqual(result.tournaments_active, 3)
        self.assertEqual(result.channels_polled, 12)
        self.assertEqual(result.ratelimit_remaining, 640)
        assert result.last_run_at is not None
        self.assertEqual(result.last_run_at.timestamp(), 1_755_300_000.0)

    async def test_missing_credentials_are_reported_separately_from_the_status(self) -> None:
        """`not_configured` and `credentials_configured` answer different questions:
        the first is what the last tick did, the second is what the environment
        holds right now. An operator who has just filled in the env but whose tick
        has not run yet needs to see the second flip before the first does."""
        self._wire(status={"ran_at": 1.0, "status": "not_configured"}, configured=False)

        result = await admin.health(object(), _request(GLOBAL_READER))

        self.assertEqual(result.status, "not_configured")
        self.assertFalse(result.credentials_configured)

    async def test_credentials_present_but_rejected(self) -> None:
        self._wire(status={"ran_at": 1.0, "status": "unauthorized"}, configured=True)

        result = await admin.health(object(), _request(GLOBAL_READER))

        self.assertEqual(result.status, "unauthorized")
        self.assertTrue(result.credentials_configured)

    async def test_corrupt_status_blob_degrades_to_never_ran(self) -> None:
        self._wire(status=None)
        admin.realtime_redis.strings[state.POLL_STATUS_KEY] = "not json"

        result = await admin.health(object(), _request(GLOBAL_READER))

        self.assertIsNone(result.status)
