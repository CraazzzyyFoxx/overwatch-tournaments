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


from shared.messaging.config import PICKUP_MIX_CHANGED_QUEUE  # noqa: E402
from shared.services.realtime import Resource, Scope  # noqa: E402
from src.services import pickup_mix_realtime  # noqa: E402


class PickupMixRealtimeTests(IsolatedAsyncioTestCase):
    """What the two rails are told, not how they deliver it.

    Realtime delivery (staging, union, publish-after-commit) is pinned once in
    ``backend/tests/test_realtime_emit.py`` and the outbox drain in
    ``backend/tests/test_outbox.py``; what matters here is the audience, the
    resource and the ids, because getting any of them wrong sends a workspace's
    roster to the wrong people or leaves a stale card in a Discord channel.
    """

    async def test_a_roster_edit_stales_the_workspace_pickup_mix(self) -> None:
        session = object()

        with (
            patch.object(pickup_mix_realtime, "emit", new=AsyncMock()) as staged,
            patch.object(pickup_mix_realtime, "enqueue_outbox_event", new=AsyncMock()),
        ):
            await pickup_mix_realtime.emit_pickup_mix_changed(
                session, 7, custom_game_id=11, change="roster", actor_user_id=9
            )

        staged.assert_awaited_once()
        args, kwargs = staged.await_args
        self.assertIs(session, args[0])
        self.assertEqual(Scope.workspace(7), kwargs["scope"])
        self.assertEqual([Resource.WORKSPACE_PICKUP_MIX], kwargs["invalidates"])
        self.assertEqual(9, kwargs["actor_user_id"])

    async def test_the_data_event_is_non_durable_and_carries_no_row_data(self) -> None:
        with (
            patch.object(pickup_mix_realtime, "emit", new=AsyncMock()) as staged,
            patch.object(pickup_mix_realtime, "enqueue_outbox_event", new=AsyncMock()),
        ):
            await pickup_mix_realtime.emit_pickup_mix_changed(object(), 7, custom_game_id=None, change="rank")

        data = staged.await_args.kwargs["data"]
        self.assertEqual("pickup_mix", data.domain)
        self.assertEqual(pickup_mix_realtime.PICKUP_MIX_UPDATED, data.event_type)
        self.assertFalse(data.durable)
        self.assertEqual({"workspace_id": 7, "change": "rank"}, dict(data.payload))

    async def test_the_change_is_queued_as_a_durable_fact_for_the_projector(self) -> None:
        """A Discord channel has no client to refetch on reconnect, so the card
        is only as fresh as the event the projector got: it goes through the
        outbox, in the mutation's own transaction."""
        session = object()

        with (
            patch.object(pickup_mix_realtime, "emit", new=AsyncMock()),
            patch.object(pickup_mix_realtime, "enqueue_outbox_event", new=AsyncMock()) as enqueued,
        ):
            await pickup_mix_realtime.emit_pickup_mix_changed(session, 7, custom_game_id=11, change="roster")

        enqueued.assert_awaited_once()
        args, kwargs = enqueued.await_args
        self.assertIs(session, args[0])
        event = args[1]
        self.assertEqual("pickup_mix.changed", event.event_type)
        self.assertEqual((7, 11, "roster"), (event.workspace_id, event.custom_game_id, event.change))
        self.assertEqual("", kwargs["exchange"])
        self.assertEqual(PICKUP_MIX_CHANGED_QUEUE.name, kwargs["routing_key"])
