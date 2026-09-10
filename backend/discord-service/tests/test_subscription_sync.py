"""Coverage for `MemberSubscriptionSyncService.resync`.

Redis is no longer touched here: cache invalidation rides the unified realtime
rail, wired once in `main.py` from `settings.redis_url`.
"""

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.config import settings as real_settings  # noqa: E402
from src.services.subscription_sync import MemberSubscriptionSyncService  # noqa: E402


class SubscriptionSyncServiceTests(IsolatedAsyncioTestCase):
    async def test_resync_skips_redis_when_no_workspace_matches(self) -> None:
        """No workspace for the guild -> returns before touching Redis or the resolver."""
        workspaces = MagicMock()
        workspaces.list_ids_by_discord_guild = AsyncMock(return_value=[])
        session = MagicMock()
        session_maker = MagicMock()
        session_maker.return_value.__aenter__ = AsyncMock(return_value=session)
        session_maker.return_value.__aexit__ = AsyncMock(return_value=False)

        service = MemberSubscriptionSyncService(
            settings=real_settings, session_maker=session_maker, workspaces=workspaces
        )

        await service.resync("999", "111", "member_join")

        session.commit.assert_not_called()
