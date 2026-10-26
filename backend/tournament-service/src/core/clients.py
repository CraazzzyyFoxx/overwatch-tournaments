"""External clients built from this service's settings.

Both are built per call rather than memoized: the Discord client memoizes a
guild's member/role lists, and that memo must not outlive the request that
filled it -- a role mapping edited mid-tournament would otherwise keep refusing
patrons it no longer applies to.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

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


def subscription_resolver(
    session: AsyncSession, *, release: Callable[[], Awaitable[None]] | None = None
) -> SubscriptionResolver:
    """Resolver wired with this service's provider credentials.

    ``release`` runs after the strategies' DB reads and before any provider call;
    the admission gate passes ``session.commit`` so no Discord/Twitch call holds a
    transaction (and its pgBouncer server connection) open.
    """
    return build_resolver(
        session,
        twitch_client_id=settings.twitch_client_id,
        token_key=settings.oauth_token_encryption_key,
        broker=optional_broker(),
        proxy=settings.proxy_url,
        release=release,
    )
