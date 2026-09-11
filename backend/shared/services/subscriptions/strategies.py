"""Wire the providers to real identities and real HTTP.

Each strategy answers "resolve these users for this provider", owning the lookup
from our ``auth_user_id`` to the external account id. That keeps the resolver
purely about config and caching.

Credentials are constructor arguments, never read from a global settings object:
``shared`` is imported by every service and must not depend on any one service's
configuration.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final

import httpx
import sqlalchemy as sa
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import SocialProvider
from shared.services.discord_client import DISCORD_API_BASE, DiscordClient
from shared.services.subscriptions import SubscriptionState, SubscriptionVerdict
from shared.services.subscriptions.providers.discord_role import DiscordRoleResolver
from shared.services.subscriptions.providers.twitch_helix import (
    HelixForbidden,
    HelixMissingScope,
    HelixNotConfigured,
    HelixNotFound,
    HelixUnavailable,
    TwitchHelixResolver,
)

__all__ = (
    "TWITCH_HELIX_BASE",
    "BoostyDiscordStrategy",
    "TwitchSubscriptionStrategy",
    "load_provider_user_ids",
)

TWITCH_HELIX_BASE: Final = "https://api.twitch.tv/helix"

_TIMEOUT: Final = httpx.Timeout(10.0, connect=5.0)

# Which of one user's per-account verdicts wins. ``unknown`` outranks
# ``inactive`` because it fails open by contract (``meets_min_tier``): an account
# we could not check must not be overruled by a sibling account that is merely
# not subscribed, or one account's outage locks a paying patron out.
_STATE_PRECEDENCE: Final[dict[str, int]] = {
    SubscriptionState.ACTIVE: 2,
    SubscriptionState.UNKNOWN: 1,
    SubscriptionState.INACTIVE: 0,
}


def _merge_account_verdicts(pairs: Sequence[tuple[str | None, SubscriptionVerdict]]) -> SubscriptionVerdict:
    """Collapse one user's per-account verdicts into the entitlement they hold.

    A user may link SEVERAL accounts of the same provider (the schema allows it
    deliberately) and the subscription sits on whichever one they happened to pay
    with, so every linked account is resolved and the strongest verdict wins.
    Resolving only the first-linked account made a patron who paid with their
    second Discord or Twitch read as "not subscribed".

    Ties keep the earliest-linked account (``max`` is stable and the loader orders
    by connection id), so the answer does not flap between equal accounts.

    The winning account is stamped into the evidence only when there was a choice
    to make: the audit trail otherwise carries no hint of WHICH account answered,
    and the single-account case must keep the evidence the resolver produced.
    """
    account_id, verdict = max(pairs, key=lambda pair: (_STATE_PRECEDENCE.get(pair[1].state, 0), pair[1].tier_rank or 1))
    if len(pairs) == 1:
        return verdict
    return replace(
        verdict,
        evidence={**verdict.evidence, "resolved_account_id": account_id, "accounts_checked": len(pairs)},
    )


async def _gather_verdicts(
    coros: list[Awaitable[tuple[int, SubscriptionVerdict]]],
    *,
    auth_user_ids: Sequence[int],
    source: str,
) -> dict[int, SubscriptionVerdict]:
    """Run per-user resolutions concurrently, degrading a crash to ``unknown``.

    ``return_exceptions`` is not optional here. Each resolver converts only its
    OWN typed errors, so an untyped escape -- a malformed 200 body making
    ``response.json()`` raise, say -- would otherwise propagate straight out of
    ``gather`` while its siblings are still scheduled. The enclosing
    ``async with httpx.AsyncClient(...)`` then closes the client under them and
    the whole batch is lost, when this module's entire failure philosophy is
    that one broken user resolves ``unknown`` and everyone else still gets a
    verdict.
    """
    settled = await asyncio.gather(*coros, return_exceptions=True)

    out: dict[int, SubscriptionVerdict] = {}
    for auth_user_id, result in zip(auth_user_ids, settled, strict=True):
        if isinstance(result, BaseException):
            logger.warning(f"subscription resolution crashed for user {auth_user_id}: {result!r}")
            out[auth_user_id] = SubscriptionVerdict(
                state="unknown",
                tier_rank=None,
                tier_label=None,
                source=source,
                checked_at=datetime.now(UTC),
                expires_at=None,
                evidence={"reason": "provider_unavailable", "error": repr(result)},
            )
        else:
            resolved_id, verdict = result
            out[resolved_id] = verdict
    return out


async def load_provider_user_ids(
    session: AsyncSession,
    *,
    auth_user_ids: Sequence[int],
    oauth_provider: str,
) -> dict[int, list[str]]:
    """Map ``auth_user_id`` -> EVERY external account id for one OAuth provider.

    A user may have several connections of the same provider (the schema allows it
    deliberately) and the subscription can sit on any of them, so all are returned,
    earliest-linked first. Returning only the lowest id silently ignored every
    account but the first: a patron who paid with their second Discord resolved as
    "not subscribed".
    """
    if not auth_user_ids:
        return {}
    rows = await session.execute(
        sa.select(models.OAuthConnection.auth_user_id, models.OAuthConnection.provider_user_id)
        .where(
            models.OAuthConnection.auth_user_id.in_(list(auth_user_ids)),
            models.OAuthConnection.provider == oauth_provider,
        )
        .order_by(models.OAuthConnection.id)
    )
    out: dict[int, list[str]] = {}
    for auth_user_id, provider_user_id in rows.all():
        if not provider_user_id:
            continue
        account_ids = out.setdefault(auth_user_id, [])
        # The same external account can be connected twice (re-link after a
        # revoke); resolving it twice would just burn a rate-limit slot.
        if provider_user_id not in account_ids:
            account_ids.append(provider_user_id)
    return out


class BoostyDiscordStrategy:
    """Boosty tiers via the Discord roles Boosty's own bot assigns.

    Every Discord read goes through ``DiscordClient``: discord-service first
    (one batch RPC answered from discord.py's guild cache), Discord's REST API
    only when that round trip fails.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        bot_token: str | None = None,
        broker: Any | None = None,
        proxy: str | None = None,
        api_base: str = DISCORD_API_BASE,
    ) -> None:
        self._session = session
        self._bot_token = bot_token
        self._broker = broker
        self._proxy = proxy
        self._api_base = api_base

    async def resolve_many(
        self, *, config: dict[str, Any], auth_user_ids: Sequence[int]
    ) -> dict[int, SubscriptionVerdict]:
        discord_ids = await load_provider_user_ids(
            self._session, auth_user_ids=auth_user_ids, oauth_provider=SocialProvider.DISCORD
        )

        # One client per batch: its member/role memo must not outlive this call.
        discord = DiscordClient(
            broker=self._broker, bot_token=self._bot_token, proxy=self._proxy, api_base=self._api_base
        )
        guild_id = str(config.get("guild_id") or "").strip() if config else ""
        if guild_id:
            await discord.prefetch(guild_id, [uid for ids in discord_ids.values() for uid in ids])

        resolver = DiscordRoleResolver(
            fetch_member_roles=discord.member_roles,
            fetch_guild_role_ids=discord.guild_role_ids,
        )
        semaphore = asyncio.Semaphore(15)

        async def _resolve_one(auth_user_id: int) -> tuple[int, SubscriptionVerdict]:
            async with semaphore:
                verdict = await self._resolve_accounts(
                    resolver, config=config, account_ids=discord_ids.get(auth_user_id) or []
                )
                return auth_user_id, verdict

        return await _gather_verdicts(
            [_resolve_one(uid) for uid in auth_user_ids],
            auth_user_ids=auth_user_ids,
            source=DiscordRoleResolver.source,
        )

    @staticmethod
    async def _resolve_accounts(
        resolver: DiscordRoleResolver, *, config: dict[str, Any], account_ids: Sequence[str]
    ) -> SubscriptionVerdict:
        """Resolve every Discord account this user linked and keep the best verdict."""
        # `[None]` when nothing is linked: the resolver owns the
        # `no_linked_discord_account` verdict, so there is exactly one code path.
        candidates: list[str | None] = list(account_ids) or [None]
        return _merge_account_verdicts(
            [
                (account_id, await resolver.resolve(config=config, discord_user_id=account_id))
                for account_id in candidates
            ]
        )


class TwitchSubscriptionStrategy:
    """Twitch tiers via Helix ``GET /subscriptions/user``.

    Uses each patron's own stored user access token. A 401 means either an expired
    token or a token predating the ``user:read:subscriptions`` scope; both surface
    as ``HelixMissingScope`` so the UI offers a reconnect instead of refusing the
    patron. Refreshing the token is identity-service's job, not this module's.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        client_id: str | None,
        proxy: str | None = None,
        api_base: str = TWITCH_HELIX_BASE,
    ) -> None:
        self._session = session
        self._client_id = client_id
        self._proxy = proxy
        self._api_base = api_base

    async def resolve_many(
        self, *, config: dict[str, Any], auth_user_ids: Sequence[int]
    ) -> dict[int, SubscriptionVerdict]:
        connections = await self._load_connections(auth_user_ids)

        async with httpx.AsyncClient(proxy=self._proxy, timeout=_TIMEOUT) as client:
            semaphore = asyncio.Semaphore(15)

            async def _resolve_one(auth_user_id: int) -> tuple[int, SubscriptionVerdict]:
                async with semaphore:
                    # `[(None, None)]` when nothing is linked: the resolver owns the
                    # `no_linked_twitch_account` verdict, so one code path serves both.
                    accounts: list[tuple[str | None, str | None]] = list(connections.get(auth_user_id) or [])
                    pairs: list[tuple[str | None, SubscriptionVerdict]] = []
                    for twitch_user_id, token in accounts or [(None, None)]:
                        # One resolver per account: the access token is per account.
                        resolver = TwitchHelixResolver(check_subscription=self._checker(client, token))
                        verdict = await resolver.resolve(config=config, twitch_user_id=twitch_user_id)
                        pairs.append((twitch_user_id, verdict))
                    return auth_user_id, _merge_account_verdicts(pairs)

            return await _gather_verdicts(
                [_resolve_one(uid) for uid in auth_user_ids],
                auth_user_ids=auth_user_ids,
                source=TwitchHelixResolver.source,
            )

    async def _load_connections(self, auth_user_ids: Sequence[int]) -> dict[int, list[tuple[str, str | None]]]:
        """Map ``auth_user_id`` -> every Twitch connection, earliest-linked first.

        All of them, not just the first: the subscription can sit on any account the
        patron linked, and each one carries its own access token.
        """
        if not auth_user_ids:
            return {}
        rows = await self._session.execute(
            sa.select(
                models.OAuthConnection.auth_user_id,
                models.OAuthConnection.provider_user_id,
                models.OAuthConnection.access_token,
            )
            .where(
                models.OAuthConnection.auth_user_id.in_(list(auth_user_ids)),
                models.OAuthConnection.provider == SocialProvider.TWITCH,
            )
            .order_by(models.OAuthConnection.id)
        )
        out: dict[int, list[tuple[str, str | None]]] = {}
        for auth_user_id, provider_user_id, access_token in rows.all():
            if not provider_user_id:
                continue
            connections = out.setdefault(auth_user_id, [])
            if all(existing != provider_user_id for existing, _ in connections):
                connections.append((provider_user_id, access_token))
        return out

    def _checker(self, client: httpx.AsyncClient, token: str | None) -> Callable[..., Awaitable[dict[str, Any]]]:
        async def check(*, broadcaster_id: str, user_id: str) -> dict[str, Any]:
            if not self._client_id:
                raise HelixNotConfigured("twitch client id is not configured")
            if not token:
                raise HelixMissingScope("no usable twitch token")
            try:
                response = await client.get(
                    f"{self._api_base}/subscriptions/user",
                    params={"broadcaster_id": broadcaster_id, "user_id": user_id},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Client-Id": self._client_id,
                    },
                )
            except httpx.HTTPError as exc:
                raise HelixUnavailable(str(exc)) from exc
            if response.status_code == 404:
                raise HelixNotFound("not subscribed")
            if response.status_code == 401:
                raise HelixMissingScope("401 from helix")
            if response.status_code in (400, 403):
                raise HelixForbidden(f"status {response.status_code}")
            if response.status_code != 200:
                raise HelixUnavailable(f"status {response.status_code}")
            result: dict[str, Any] = response.json()
            return result

        return check
