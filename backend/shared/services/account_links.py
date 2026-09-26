"""Which of the account links a self-service mix signup requires are missing.

Two providers, and both for a concrete reason: Discord because the bot can only
act for an account that linked the Discord user who clicked, Battle.net because a
mix roster row is named after a BattleTag and its ranks are resolved through the
player identity that link creates.

Reading ``auth`` through shared is allowed here (backend/ARCHITECTURE.md:293) --
this is a read of one OAuth table, not identity business logic.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider
from shared.repository import OAuthConnectionRepository

__all__ = ("REQUIRED_LINK_PROVIDERS", "missing_account_links")

#: Order is the order a caller reports a blocker in, so it matches the admission
#: table in docs/mix-self-signup-discord/design.md.
REQUIRED_LINK_PROVIDERS: tuple[str, ...] = (SocialProvider.DISCORD, SocialProvider.BATTLENET)

_connections = OAuthConnectionRepository()


async def missing_account_links(session: AsyncSession, auth_user_id: int) -> frozenset[str]:
    """The subset of :data:`REQUIRED_LINK_PROVIDERS` this account has no OAuth row for."""
    rows = await _connections.list_by_user_providers(
        session, auth_user_id=auth_user_id, providers=list(REQUIRED_LINK_PROVIDERS)
    )
    linked = {row.provider for row in rows}
    return frozenset(provider for provider in REQUIRED_LINK_PROVIDERS if provider not in linked)
