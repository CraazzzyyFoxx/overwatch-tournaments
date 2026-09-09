"""The wiring builds and registers the providers the design promises.

Cheap guard against a broken import or a renamed provider key: the resolver reads
``provider_config.provider`` values straight out of the database, so a mismatch
between those strings and the strategy registry keys silently degrades every
verdict to ``no_strategy_for_provider`` (unknown, fail-open) — the gate stops
enforcing and nothing errors.

``TestCredentialsAreReportedHonestly`` pins the reported bug: neither service that
resolves subscriptions was given ``DISCORD_TOKEN``/``TWITCH_CLIENT_ID``, and the
strategies reported that as ``guild_not_accessible`` / ``missing_scope`` -- a guild
fault and a patron's stale token, when in truth we simply had no credential. The
credential is deployment config and can go missing again; the reason must not lie
about whose problem it is.
"""

from __future__ import annotations

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from shared.core.social import SocialProvider
from shared.services.subscriptions import SubscriptionState
from shared.services.subscriptions import strategies as strategies_module
from shared.services.subscriptions.entitlements import SubscriptionResolver
from shared.services.subscriptions.strategies import TwitchSubscriptionStrategy
from shared.services.subscriptions.wiring import build_event_sink, build_resolver, build_strategies


class TestBuildStrategies:
    def test_registers_boosty_and_twitch(self):
        strategies = build_strategies(None)  # type: ignore[arg-type]
        assert set(strategies) == {SocialProvider.BOOSTY, SocialProvider.TWITCH}

    def test_keys_are_the_canonical_social_provider_strings(self):
        """These strings are stored in the DB; they must not drift."""
        strategies = build_strategies(None)  # type: ignore[arg-type]
        assert set(strategies) == {"boosty", "twitch"}

    def test_strategies_expose_resolve_many(self):
        for strategy in build_strategies(None).values():  # type: ignore[arg-type]
            assert callable(getattr(strategy, "resolve_many", None))

    def test_builds_without_credentials(self):
        """Missing credentials must not raise at construction: the resolver has to
        be buildable so it can report a reasoned `unknown` per user."""
        assert build_strategies(None, discord_bot_token=None, twitch_client_id=None)  # type: ignore[arg-type]


class TestBuildResolver:
    def test_returns_a_resolver(self):
        assert isinstance(build_resolver(None), SubscriptionResolver)  # type: ignore[arg-type]

    def test_passes_credentials_through(self):
        resolver = build_resolver(
            None,  # type: ignore[arg-type]
            discord_bot_token="bot-token",
            twitch_client_id="client-id",
        )
        assert isinstance(resolver, SubscriptionResolver)


class TestBuildEventSink:
    def test_the_sink_rides_the_session_it_is_built_from(self):
        """No optional wiring left: the signal is staged on the resolver's own
        transaction, so there is no configuration under which a resolver
        silently cannot invalidate anybody's page."""
        sink = build_event_sink(None)  # type: ignore[arg-type]
        assert callable(getattr(sink, "subscriptions_updated", None))


class TestCredentialsAreReportedHonestly(IsolatedAsyncioTestCase):
    async def _resolve(self, provider: str, config: dict) -> str:
        strategy = build_strategies(None, discord_bot_token=None, twitch_client_id=None)[provider]  # type: ignore[arg-type]
        with patch.object(strategies_module, "load_provider_user_ids", AsyncMock(return_value={1: ["external-id"]})):
            with patch.object(
                TwitchSubscriptionStrategy, "_load_connections", AsyncMock(return_value={1: [("777", "token")]})
            ):
                verdicts = await strategy.resolve_many(config=config, auth_user_ids=[1])
        assert verdicts[1].state == SubscriptionState.UNKNOWN
        return str(verdicts[1].evidence.get("reason"))

    async def test_boosty_without_a_bot_token_blames_the_token_not_the_guild(self):
        reason = await self._resolve(
            SocialProvider.BOOSTY,
            {"guild_id": "1234567890123456789", "role_tiers": [{"role_id": "9", "tier_rank": 1}]},
        )
        assert reason == "bot_not_configured"

    async def test_twitch_without_a_client_id_does_not_ask_the_patron_to_reconnect(self):
        reason = await self._resolve(SocialProvider.TWITCH, {"broadcaster_id": "42"})
        assert reason == "twitch_client_not_configured"
