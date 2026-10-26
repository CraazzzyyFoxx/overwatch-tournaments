"""A failed Discord batch costs one round trip, not one more per linked account.

When discord-service does not answer the batch RPC (5 s), asking again per
account just waits out the same failure once per account while the caller holds
its connection. Stdlib unittest like its siblings; the broker is a mock.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from shared.services.subscriptions import SubscriptionState
from shared.services.subscriptions.strategies import BoostyDiscordStrategy

CONFIG = {"guild_id": "999", "role_tiers": [{"role_id": "100", "tier_rank": 1}]}


class TestFailedBatch(IsolatedAsyncioTestCase):
    async def test_every_linked_account_files_the_outage_without_asking_again(self) -> None:
        broker = AsyncMock()
        broker.request.side_effect = TimeoutError("discord-service did not answer")
        strategy = BoostyDiscordStrategy(AsyncMock(), broker=broker)

        with patch(
            "shared.services.subscriptions.strategies.load_provider_user_ids",
            AsyncMock(return_value={1: ["a"], 2: ["b", "c"]}),
        ):
            verdicts = await strategy.resolve_many(config=CONFIG, auth_user_ids=[1, 2, 3])

        broker.request.assert_awaited_once()
        for auth_user_id in (1, 2):
            assert verdicts[auth_user_id].state == SubscriptionState.UNKNOWN
            assert verdicts[auth_user_id].evidence["reason"] == "provider_unavailable"
        # An unlinked user keeps its own verdict; it was never part of the batch.
        assert verdicts[3].evidence["reason"] == "no_linked_discord_account"
