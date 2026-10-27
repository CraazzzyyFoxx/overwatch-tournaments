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

from collections.abc import Awaitable, Callable
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
    twitch_client_id: str | None = None,
    token_key: str | None = None,
    broker: Any | None = None,
    proxy: str | None = None,
    release: Callable[[], Awaitable[None]] | None = None,
) -> dict[str, ProviderStrategy]:
    """Map ``provider`` -> live resolution strategy.

    Keys are the entitlement providers stored in ``provider_config.provider``
    (``boosty``/``twitch``), not the mechanism that answers: Boosty's tier comes
    from Discord roles, which is an implementation detail recorded in the
    verdict's ``source``. Discord is asked through ``broker`` (discord-service
    holds the only bot token); ``proxy`` is Twitch's egress and ``token_key``
    (``OAUTH_TOKEN_ENCRYPTION_KEY``) opens the patrons' stored Twitch tokens.
    ``release`` runs after each strategy's DB read, before its first network call
    (e.g. ``session.commit``, so no provider call waits inside a transaction).

    A provider with no credentials is still registered: its strategy resolves to
    ``unknown`` with a reason, which is strictly better than the resolver
    reporting ``no_strategy_for_provider`` and hiding the real cause.
    """
    return {
        SocialProvider.BOOSTY: BoostyDiscordStrategy(session, broker=broker, release=release),
        SocialProvider.TWITCH: TwitchSubscriptionStrategy(
            session, client_id=twitch_client_id, token_key=token_key, proxy=proxy, release=release
        ),
    }


def build_resolver(
    session: AsyncSession,
    *,
    twitch_client_id: str | None = None,
    token_key: str | None = None,
    broker: Any | None = None,
    proxy: str | None = None,
    release: Callable[[], Awaitable[None]] | None = None,
) -> SubscriptionResolver:
    return SubscriptionResolver(
        store=build_store(session),
        strategies=build_strategies(
            session,
            twitch_client_id=twitch_client_id,
            token_key=token_key,
            broker=broker,
            proxy=proxy,
            release=release,
        ),
        # Every real resolver records history: the collector needs it for the admin
        # tab, and the registration/check-in gates are exactly the checks an
        # organizer later asks "why was this player refused?" about.
        log_sink=build_log_sink(session),
        # ...and tells the workspace when a verdict actually moved, so an open page
        # shows it without polling.
        event_sink=build_event_sink(session),
    )
