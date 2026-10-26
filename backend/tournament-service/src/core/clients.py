"""External clients built from this service's settings.

Both are built per call rather than memoized: the Discord client memoizes a
guild's member/role lists, and that memo must not outlive the request that
filled it -- a role mapping edited mid-tournament would otherwise keep refusing
patrons it no longer applies to.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.services.discord_client import DiscordClient
from shared.services.subscriptions.entitlements import SubscriptionResolver
from shared.services.subscriptions.wiring import build_resolver
from src.core.broker import optional_broker
from src.core.config import settings

__all__ = ("discord_client", "subscription_resolver")


def discord_client() -> DiscordClient:
    """discord-service over RabbitMQ; this service holds no bot token."""
    return DiscordClient(broker=optional_broker())


def subscription_resolver(session: AsyncSession) -> SubscriptionResolver:
    """Resolver wired with this service's provider credentials."""
    return build_resolver(
        session,
        twitch_client_id=settings.twitch_client_id,
        token_key=settings.oauth_token_encryption_key,
        broker=optional_broker(),
        proxy=settings.proxy_url,
    )
