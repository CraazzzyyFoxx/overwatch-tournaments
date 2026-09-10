"""Re-evaluates a Discord user's subscription the moment their guild membership
or roles change, instead of waiting for the next scheduled poll.
"""

from __future__ import annotations

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.core.enums import SubscriptionCollectionSource
from shared.core.social import SocialProvider
from shared.repository import OAuthConnectionRepository, WorkspaceRepository
from shared.services.subscriptions.wiring import build_resolver
from src.core.broker import optional_broker
from src.core.config import Settings


class MemberSubscriptionSyncService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_maker: async_sessionmaker[AsyncSession],
        workspaces: WorkspaceRepository = WorkspaceRepository(),
        oauth_connections: OAuthConnectionRepository = OAuthConnectionRepository(),
    ) -> None:
        self._settings = settings
        self._session_maker = session_maker
        self._workspaces = workspaces
        self._oauth_connections = oauth_connections

    async def resync(self, guild_id: str, discord_user_id: str, reason: str) -> None:
        """Re-evaluates Boosty subscription for a Discord user whose member state/roles changed."""
        try:
            async with self._session_maker() as session:
                workspace_ids = await self._workspaces.list_ids_by_discord_guild(session, guild_id)
                if not workspace_ids:
                    return

                connection = await self._oauth_connections.get_by_provider_subject(
                    session, provider=SocialProvider.DISCORD, provider_user_id=discord_user_id
                )
                if connection is None:
                    return
                auth_user_ids = [connection.auth_user_id]

                resolver = build_resolver(
                    session,
                    discord_bot_token=self._settings.discord_token,
                    broker=optional_broker(),
                )
                for ws_id in workspace_ids:
                    await resolver.resolve(
                        workspace_id=ws_id,
                        auth_user_ids=auth_user_ids,
                        providers=[SocialProvider.BOOSTY],
                        force_refresh=True,
                        source=SubscriptionCollectionSource.scheduled,
                    )
                await session.commit()
                logger.info(
                    f"⚡ Instant subscription update for user(s) {auth_user_ids} "
                    f"in workspace(s) {workspace_ids} (reason={reason})"
                )

        except Exception as e:
            logger.error(
                f"❌ Error handling member subscription change for user {discord_user_id} in guild {guild_id}: {e}"
            )
