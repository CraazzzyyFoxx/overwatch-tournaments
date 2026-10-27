"""Challenge-code redemption.

The fallback path for organizers without a Discord server: the author publishes a
secret code inside a subscriber-only post, the patron pastes it. This proves
ACCESS TO A LEVEL, not identity — a code is shareable — so the rules that matter
are: never downgrade an existing entitlement, never leak which code was tried,
and rate-limit the attempts because the endpoint is a guessing oracle.

Runs under stdlib unittest -- no pytest-asyncio in this repo.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import IsolatedAsyncioTestCase

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fakeredis import FakeServer  # noqa: E402
from fakeredis.aioredis import FakeRedis  # noqa: E402

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.services.subscriptions import SubscriptionSource, SubscriptionState, VerificationMethod  # noqa: E402
from shared.services.subscriptions.challenge_code import hash_code  # noqa: E402
from shared.services.subscriptions.entitlements import (  # noqa: E402
    ProviderConfigRow,
    StoredEntitlement,
)
from src.services.registration.subscription_codes import redeem_challenge_code  # noqa: E402
from src.services.registration.subscription_status import (  # noqa: E402
    REDEEM_ATTEMPT_LIMIT,
    assert_redeem_attempt_allowed,
)

NOW = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)
WS = 7
USER = 42


def _config(*codes, enabled=True, method=None):
    config: dict = {"codes": list(codes)}
    if method is not None:
        config["verification_method"] = method
    return ProviderConfigRow(provider="boosty", enabled=enabled, config=config)


def _code(plain: str, tier: int, *, label: str | None = None, expires=None):
    row = {"code_sha256": hash_code(plain), "tier_rank": tier}
    if label:
        row["tier_label"] = label
    if expires is not None:
        row["expires_at"] = expires.isoformat()
    return row


def _stored(state, tier, source=SubscriptionSource.CHALLENGE_CODE, expires_in=86_400):
    return StoredEntitlement(
        state=state,
        tier_rank=tier,
        tier_label=None,
        source=source,
        checked_at=NOW,
        expires_at=NOW + timedelta(seconds=expires_in),
        evidence={},
    )


class _Store:
    def __init__(self, configs=None, stored=None):
        self._configs = configs or {}
        self._stored = stored or {}
        self.upserts = []

    async def load_configs(self, workspace_id, providers):
        return {p: self._configs[p] for p in providers if p in self._configs}

    async def load_entitlements(self, workspace_id, auth_user_ids, providers):
        return {k: v for k, v in self._stored.items() if k[0] in set(auth_user_ids) and k[1] in set(providers)}

    async def upsert(self, workspace_id, auth_user_id, provider, verdict):
        self.upserts.append((workspace_id, auth_user_id, provider, verdict))


async def _redeem(store, code, *, provider="boosty", now=NOW):
    return await redeem_challenge_code(
        store=store,
        workspace_id=WS,
        auth_user_id=USER,
        provider=provider,
        submitted_code=code,
        now=now,
    )


class TestSuccessfulRedemption(IsolatedAsyncioTestCase):
    async def test_valid_code_creates_an_active_entitlement(self):
        store = _Store({"boosty": _config(_code("secret", 2, label="Уровень 2"))})
        verdict = await _redeem(store, "secret")
        assert verdict.state == SubscriptionState.ACTIVE
        assert verdict.tier_rank == 2
        assert verdict.tier_label == "Уровень 2"
        assert verdict.source == SubscriptionSource.CHALLENGE_CODE
        assert len(store.upserts) == 1

    async def test_code_is_normalized_before_matching(self):
        """Patrons paste out of a post; casing and stray spaces are noise."""
        store = _Store({"boosty": _config(_code("secret", 1))})
        verdict = await _redeem(store, "  SECRET  ")
        assert verdict.state == SubscriptionState.ACTIVE

    async def test_highest_tier_wins_on_duplicate_code(self):
        store = _Store({"boosty": _config(_code("secret", 1), _code("secret", 3))})
        verdict = await _redeem(store, "secret")
        assert verdict.tier_rank == 3

    async def test_persisted_verdict_expires_with_the_code(self):
        """A redeemed code is conclusive until its own expiry, not on a TTL."""
        expires = NOW + timedelta(days=30)
        store = _Store({"boosty": _config(_code("secret", 1, expires=expires))})
        verdict = await _redeem(store, "secret")
        assert verdict.expires_at == expires

    async def test_code_without_expiry_gets_no_expiry(self):
        store = _Store({"boosty": _config(_code("secret", 1))})
        verdict = await _redeem(store, "secret")
        assert verdict.expires_at is None

    async def test_evidence_records_the_redemption_not_the_code(self):
        """Never persist or echo the plaintext secret."""
        store = _Store({"boosty": _config(_code("secret", 2))})
        verdict = await _redeem(store, "secret")
        assert verdict.evidence.get("reason") == "code_redeemed"
        assert "secret" not in str(verdict.evidence)


class TestRejection(IsolatedAsyncioTestCase):
    async def test_wrong_code_raises_and_writes_nothing(self):
        store = _Store({"boosty": _config(_code("secret", 2))})
        with self.assertRaises(HTTPException) as ctx:
            await _redeem(store, "nope")
        assert ctx.exception.status_code == 400
        assert [item["code"] for item in ctx.exception.detail] == ["subscription_code_rejected"]
        assert store.upserts == []

    async def test_expired_code_is_rejected(self):
        store = _Store({"boosty": _config(_code("secret", 2, expires=NOW - timedelta(seconds=1)))})
        with self.assertRaises(HTTPException):
            await _redeem(store, "secret")

    async def test_empty_submission_is_rejected(self):
        store = _Store({"boosty": _config(_code("secret", 2))})
        for bad in ("", "   ", None):
            with self.assertRaises(HTTPException):
                await _redeem(store, bad)
        assert store.upserts == []

    async def test_error_message_does_not_reveal_whether_codes_exist(self):
        """The endpoint is a guessing oracle; keep the response uniform."""
        with_codes = _Store({"boosty": _config(_code("secret", 2))})
        without = _Store({"boosty": _config()})
        messages = []
        for store in (with_codes, without):
            with self.assertRaises(HTTPException) as ctx:
                await _redeem(store, "guess")
            messages.append(ctx.exception.detail)
        assert messages[0] == messages[1]

    async def test_unconfigured_provider_is_rejected(self):
        with self.assertRaises(HTTPException):
            await _redeem(_Store(), "secret")

    async def test_disabled_provider_is_rejected(self):
        store = _Store({"boosty": _config(_code("secret", 2), enabled=False)})
        with self.assertRaises(HTTPException):
            await _redeem(store, "secret")

    async def test_provider_without_codes_is_rejected(self):
        store = _Store({"boosty": ProviderConfigRow("boosty", True, {"guild_id": "9"})})
        with self.assertRaises(HTTPException):
            await _redeem(store, "secret")


class TestNeverDowngrades(IsolatedAsyncioTestCase):
    async def test_lower_tier_code_does_not_downgrade_an_active_entitlement(self):
        """A patron on Discord tier 3 who redeems a tier-1 code keeps tier 3."""
        store = _Store(
            {"boosty": _config(_code("basic", 1))},
            {(USER, "boosty"): _stored(SubscriptionState.ACTIVE, 3)},
        )
        verdict = await _redeem(store, "basic")
        assert verdict.tier_rank == 3
        assert store.upserts == [], "nothing to write — the stored verdict already wins"

    async def test_equal_tier_code_is_a_no_op(self):
        store = _Store(
            {"boosty": _config(_code("same", 2))},
            {(USER, "boosty"): _stored(SubscriptionState.ACTIVE, 2)},
        )
        verdict = await _redeem(store, "same")
        assert verdict.tier_rank == 2
        assert store.upserts == []

    async def test_higher_tier_code_upgrades(self):
        store = _Store(
            {"boosty": _config(_code("premium", 3))},
            {(USER, "boosty"): _stored(SubscriptionState.ACTIVE, 1)},
        )
        verdict = await _redeem(store, "premium")
        assert verdict.tier_rank == 3
        assert len(store.upserts) == 1

    async def test_code_overrides_an_inactive_entitlement(self):
        store = _Store(
            {"boosty": _config(_code("secret", 1))},
            {(USER, "boosty"): _stored(SubscriptionState.INACTIVE, None)},
        )
        verdict = await _redeem(store, "secret")
        assert verdict.state == SubscriptionState.ACTIVE
        assert len(store.upserts) == 1

    async def test_code_overrides_an_expired_higher_tier(self):
        """An expired tier 3 must not block redeeming a live tier 1."""
        store = _Store(
            {"boosty": _config(_code("secret", 1))},
            {(USER, "boosty"): _stored(SubscriptionState.ACTIVE, 3, expires_in=-1)},
        )
        verdict = await _redeem(store, "secret")
        assert verdict.tier_rank == 1
        assert len(store.upserts) == 1

    async def test_discord_sourced_higher_tier_still_wins(self):
        """Source does not matter for the comparison — only the tier does."""
        store = _Store(
            {"boosty": _config(_code("basic", 1))},
            {(USER, "boosty"): _stored(SubscriptionState.ACTIVE, 2, source=SubscriptionSource.DISCORD_ROLE)},
        )
        verdict = await _redeem(store, "basic")
        assert verdict.tier_rank == 2
        assert store.upserts == []


class TestVerificationMethodGatesRedemption(IsolatedAsyncioTestCase):
    async def test_live_only_refuses_even_a_correct_code(self):
        """The organizer chose account linking; a valid code is the wrong mechanism
        and must not quietly grant a tier."""
        store = _Store({"boosty": _config(_code("secret", 2), method=VerificationMethod.LIVE)})
        with self.assertRaises(HTTPException) as caught:
            await _redeem(store, "secret")
        assert caught.exception.status_code == 400
        assert store.upserts == []

    async def test_the_refusal_says_why_instead_of_blaming_the_copy_paste(self):
        """Whether codes are accepted is public config, identical for every
        submitted code, so it is not an oracle — and 'check your copy-paste' would
        send the patron hunting for a typo that does not exist."""
        store = _Store({"boosty": _config(_code("secret", 2), method=VerificationMethod.LIVE)})
        with self.assertRaises(HTTPException) as caught:
            await _redeem(store, "secret")
        assert [item["code"] for item in caught.exception.detail] == ["subscription_code_not_accepted"]

    async def test_code_only_accepts_the_code(self):
        store = _Store({"boosty": _config(_code("secret", 2), method=VerificationMethod.CODE)})
        verdict = await _redeem(store, "secret")
        assert verdict.state == SubscriptionState.ACTIVE
        assert verdict.tier_rank == 2

    async def test_any_accepts_the_code(self):
        store = _Store({"boosty": _config(_code("secret", 1), method=VerificationMethod.ANY)})
        assert (await _redeem(store, "secret")).tier_rank == 1

    async def test_a_config_without_the_field_still_accepts_codes(self):
        """Every tournament configured before the picker existed keeps working."""
        store = _Store({"boosty": _config(_code("secret", 1))})
        assert (await _redeem(store, "secret")).tier_rank == 1

    async def test_a_wrong_code_under_code_only_keeps_the_uniform_rejection(self):
        """The oracle discipline still applies where a secret is actually at stake."""
        store = _Store({"boosty": _config(_code("secret", 1), method=VerificationMethod.CODE)})
        with self.assertRaises(HTTPException) as caught:
            await _redeem(store, "wrong")
        assert [item["code"] for item in caught.exception.detail] == ["subscription_code_rejected"]


class TestRedeemRateLimit(IsolatedAsyncioTestCase):
    async def test_the_attempt_past_the_limit_is_refused_with_a_code(self):
        """The client translates the code; a bare sentence left English users reading Russian."""
        redis = FakeRedis(server=FakeServer(), decode_responses=True)
        for _ in range(REDEEM_ATTEMPT_LIMIT):
            await assert_redeem_attempt_allowed(workspace_id=WS, auth_user_id=USER, redis=redis)
        with self.assertRaises(HTTPException) as caught:
            await assert_redeem_attempt_allowed(workspace_id=WS, auth_user_id=USER, redis=redis)
        assert caught.exception.status_code == 429
        assert [item["code"] for item in caught.exception.detail] == ["subscription_redeem_rate_limited"]
