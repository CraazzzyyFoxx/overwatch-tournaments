"""Build a ready-to-use ``SubscriptionResolver``.

Also the place where conformance to the ports is proven *statically*: these
factories are annotated to return ``EntitlementStore`` / ``ProviderStrategy``, so
mypy checks the SQL store and the real strategies against the protocols the
resolver depends on. Without an annotated assignment somewhere, a wrong signature
would only surface at runtime.

Credentials arrive as arguments -- ``shared`` is imported by every service and
must not read any single service's settings.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider
from shared.services.subscriptions.entitlements import (
    CheckLogSink,
    EntitlementStore,
    ProviderStrategy,
    SubscriptionEventSink,
    SubscriptionResolver,
)
from shared.services.subscriptions.realtime import SessionSubscriptionEventSink
from shared.services.subscriptions.store import SqlCheckLogSink, SqlEntitlementStore
from shared.services.subscriptions.strategies import (
    BoostyDiscordStrategy,
    TwitchSubscriptionStrategy,
)

__all__ = ("build_event_sink", "build_log_sink", "build_resolver", "build_store", "build_strategies")


def build_log_sink(session: AsyncSession) -> CheckLogSink:
    return SqlCheckLogSink(session)


def build_event_sink(session: AsyncSession) -> SubscriptionEventSink:
    """Realtime invalidation sink, riding the resolver's own transaction.

    Takes no Redis: the signal is staged on the session and published from its
    ``after_commit``, so there is no client to thread through and no way for a
    caller to end up with a resolver that silently signals nothing.
    """
    return SessionSubscriptionEventSink(session)


def build_store(session: AsyncSession) -> EntitlementStore:
    return SqlEntitlementStore(session)


def build_strategies(
    session: AsyncSession,
    *,
    discord_bot_token: str | None = None,
    twitch_client_id: str | None = None,
    broker: Any | None = None,
    proxy: str | None = None,
) -> dict[str, ProviderStrategy]:
    """Map ``provider`` -> live resolution strategy.

    Keys are the entitlement providers stored in ``provider_config.provider``
    (``boosty``/``twitch``), not the mechanism used to answer: Boosty's tier comes
    from Discord roles, which is an implementation detail recorded in the
    verdict's ``source``.

    A provider with no credentials is still registered: its strategy resolves to
    ``unknown`` (fail open) with a reason, which is strictly better than the
    resolver reporting ``no_strategy_for_provider`` and hiding the real cause.
    """
    return {
        SocialProvider.BOOSTY: BoostyDiscordStrategy(session, bot_token=discord_bot_token, broker=broker, proxy=proxy),
        SocialProvider.TWITCH: TwitchSubscriptionStrategy(session, client_id=twitch_client_id, proxy=proxy),
    }


def build_resolver(
    session: AsyncSession,
    *,
    discord_bot_token: str | None = None,
    twitch_client_id: str | None = None,
    broker: Any | None = None,
    proxy: str | None = None,
) -> SubscriptionResolver:
    return SubscriptionResolver(
        store=build_store(session),
        strategies=build_strategies(
            session,
            discord_bot_token=discord_bot_token,
            twitch_client_id=twitch_client_id,
            broker=broker,
            proxy=proxy,
        ),
        # Every real resolver records history: the collector needs it for the admin
        # tab, and the registration/check-in gates are exactly the checks an
        # organizer later asks "why was this player refused?" about.
        log_sink=build_log_sink(session),
        # ...and tells the workspace when a verdict actually moved, so an open page
        # shows it without polling.
        event_sink=build_event_sink(session),
    )
