from __future__ import annotations

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"
for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


from shared.services.realtime import Resource, Scope  # noqa: E402
from src.services import pickup_mix_realtime  # noqa: E402


class PickupMixRealtimeTests(IsolatedAsyncioTestCase):
    """What the rail is told, not how it delivers it.

    Delivery (staging, union, publish-after-commit) is pinned once in
    ``backend/tests/test_realtime_emit.py``; what matters here is the audience
    and the resource, because getting either wrong sends a workspace's roster
    to the wrong people or leaves a stale one on screen.
    """

    async def test_a_roster_edit_stales_the_workspace_pickup_mix(self) -> None:
        session = object()

        with patch.object(pickup_mix_realtime, "emit", new=AsyncMock()) as staged:
            await pickup_mix_realtime.emit_pickup_mix_updated(session, 7, change="roster", actor_user_id=9)

        staged.assert_awaited_once()
        args, kwargs = staged.await_args
        self.assertIs(session, args[0])
        self.assertEqual(Scope.workspace(7), kwargs["scope"])
        self.assertEqual([Resource.WORKSPACE_PICKUP_MIX], kwargs["invalidates"])
        self.assertEqual(9, kwargs["actor_user_id"])

    async def test_the_data_event_is_non_durable_and_carries_no_row_data(self) -> None:
        with patch.object(pickup_mix_realtime, "emit", new=AsyncMock()) as staged:
            await pickup_mix_realtime.emit_pickup_mix_updated(object(), 7, change="rank")

        data = staged.await_args.kwargs["data"]
        self.assertEqual("pickup_mix", data.domain)
        self.assertEqual(pickup_mix_realtime.PICKUP_MIX_UPDATED, data.event_type)
        self.assertFalse(data.durable)
        self.assertEqual({"workspace_id": 7, "change": "rank"}, dict(data.payload))
