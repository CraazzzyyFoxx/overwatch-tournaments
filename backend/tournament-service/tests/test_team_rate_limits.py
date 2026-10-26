"""Per-actor rate limits on the public team-registration flows.

The asymmetry is the point: invite fails **closed**, accept fails **open**. Both
directions are asserted, because "make them uniform" is the obvious-looking
simplification and it is wrong in one direction or the other whichever way you
pick.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase, mock

SERVICE_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = SERVICE_ROOT.parent
for path in (str(SERVICE_ROOT), str(BACKEND_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


from fakeredis import FakeServer  # noqa: E402
from fakeredis.aioredis import FakeRedis  # noqa: E402
from redis.exceptions import RedisError  # noqa: E402

from shared.core.errors import ApiHTTPException  # noqa: E402
from src.services.registration import team_rate_limits as limits  # noqa: E402


def _code(exc: ApiHTTPException) -> str:
    detail: Any = exc.detail
    return detail[0]["code"]


class _Redis(FakeRedis):
    """A real Redis command interpreter (MULTI, SET NX EX, TTLs) with its own keyspace."""

    def __init__(self) -> None:
        super().__init__(server=FakeServer(), decode_responses=True)


class _BrokenRedis:
    def pipeline(self, transaction: bool = True) -> Any:
        raise RedisError("connection lost")


class InviteLimitTests(IsolatedAsyncioTestCase):
    async def test_attempts_within_the_limit_pass(self) -> None:
        redis = _Redis()
        for _ in range(limits.INVITE_ATTEMPT_LIMIT):
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=redis)  # type: ignore[arg-type]

    async def test_one_over_the_limit_is_refused(self) -> None:
        redis = _Redis()
        for _ in range(limits.INVITE_ATTEMPT_LIMIT):
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        with self.assertRaises(ApiHTTPException) as caught:
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        self.assertEqual(429, caught.exception.status_code)
        self.assertEqual("invite_rate_limited", _code(caught.exception))

    async def test_the_window_is_set_once_not_on_every_attempt(self) -> None:
        """Re-expiring on each hit would make the window slide forever and the
        limiter unreachable for a steady attacker."""
        redis = _Redis()
        await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        await redis.expire("regteam:invite:1:2", 5)  # the window is nearly over
        await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        self.assertLessEqual(await redis.ttl("regteam:invite:1:2"), 5)

    async def test_actors_are_metered_separately(self) -> None:
        redis = _Redis()
        for _ in range(limits.INVITE_ATTEMPT_LIMIT):
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        # A different captain has their own budget.
        await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=3, redis=redis)  # type: ignore[arg-type]

    async def test_tournaments_are_metered_separately(self) -> None:
        redis = _Redis()
        for _ in range(limits.INVITE_ATTEMPT_LIMIT):
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        await limits.assert_invite_attempt_allowed(tournament_id=9, auth_user_id=2, redis=redis)  # type: ignore[arg-type]

    async def test_a_redis_failure_closes_the_door(self) -> None:
        """Invite mints a bearer credential, so losing the meter must not turn it
        into an unmetered amplifier."""
        with self.assertRaises(ApiHTTPException) as caught:
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=_BrokenRedis())  # type: ignore[arg-type]
        self.assertEqual("rate_limit_unavailable", _code(caught.exception))

    async def test_the_outage_is_a_503_not_a_429(self) -> None:
        """The actor did nothing wrong; telling them to slow down would be a lie
        about whose fault it is."""
        with self.assertRaises(ApiHTTPException) as caught:
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=_BrokenRedis())  # type: ignore[arg-type]
        self.assertEqual(503, caught.exception.status_code)


class AcceptLimitTests(IsolatedAsyncioTestCase):
    async def test_attempts_within_the_limit_pass(self) -> None:
        redis = _Redis()
        for _ in range(limits.ACCEPT_ATTEMPT_LIMIT):
            await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]

    async def test_one_over_the_limit_is_refused(self) -> None:
        redis = _Redis()
        for _ in range(limits.ACCEPT_ATTEMPT_LIMIT):
            await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        with self.assertRaises(ApiHTTPException) as caught:
            await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        self.assertEqual("accept_rate_limited", _code(caught.exception))

    async def test_a_redis_failure_lets_the_invitee_through(self) -> None:
        """The opposite of invite, deliberately: what a limiter protects here is a
        256-bit token against guessing, which is already infeasible. Blocking real
        invitees during a Redis blip is the worse outcome — and this matches the
        challenge-code limiter's documented choice."""
        await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=_BrokenRedis())  # type: ignore[arg-type]

    async def test_the_key_is_not_tournament_scoped(self) -> None:
        """A redeemer has no tournament id before the token lookup, and the account
        is the tighter bound anyway."""
        redis = _Redis()
        await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        self.assertEqual(["regteam:accept:2"], await redis.keys())


class _ExpireFails(_Redis):
    """The connection drops on the client's own EXPIRE, after INCR already counted."""

    async def expire(self, *args: Any, **kwargs: Any) -> Any:
        raise RedisError("connection lost")


class AtomicCounterTests(IsolatedAsyncioTestCase):
    async def test_a_failure_after_the_count_cannot_leave_a_key_without_expiry(self) -> None:
        """INCR and a separate EXPIRE left the key forever when the second call was
        lost: a permanent 429 for that actor. The window rides in the same MULTI."""
        redis = _ExpireFails()
        await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=redis)
        self.assertGreater(await redis.ttl("regteam:accept:2"), 0)

    async def test_concurrent_attempts_each_count_once_inside_one_window(self) -> None:
        redis = _Redis()
        await asyncio.gather(*(limits.assert_accept_attempt_allowed(auth_user_id=2, redis=redis) for _ in range(10)))
        self.assertEqual("10", await redis.get("regteam:accept:2"))
        self.assertTrue(0 < await redis.ttl("regteam:accept:2") <= limits.ACCEPT_WINDOW_SECONDS)

    async def test_a_counter_left_without_expiry_gets_its_window_back(self) -> None:
        """A key the old INCR-then-EXPIRE code stranded without a TTL (a permanent
        429) heals on the next attempt instead of staying forever."""
        redis = _Redis()
        await redis.set("regteam:accept:2", limits.ACCEPT_ATTEMPT_LIMIT + 5)
        with self.assertRaises(ApiHTTPException):
            await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=redis)  # type: ignore[arg-type]
        self.assertTrue(0 < await redis.ttl("regteam:accept:2") <= limits.ACCEPT_WINDOW_SECONDS)


class FailDirectionContractTests(IsolatedAsyncioTestCase):
    async def test_the_two_directions_genuinely_differ(self) -> None:
        """One assertion covering the whole design decision: the same Redis outage
        stops an invite and lets an acceptance through. If a refactor unifies them,
        exactly one of these two lines fails."""
        with self.assertRaises(ApiHTTPException):
            await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2, redis=_BrokenRedis())  # type: ignore[arg-type]
        await limits.assert_accept_attempt_allowed(auth_user_id=2, redis=_BrokenRedis())  # type: ignore[arg-type]

    async def test_a_missing_client_is_treated_like_an_outage(self) -> None:
        """``_consume`` must return the same "no verdict" for a Redis error and for
        no client at all — otherwise a misconfigured deployment runs unmetered while
        a broken one is blocked, which is backwards."""
        with mock.patch.object(limits, "_client", return_value=None):
            self.assertIsNone(await limits._consume("k", limit=1, window_seconds=60, redis=None))
            with self.assertRaises(ApiHTTPException) as caught:
                await limits.assert_invite_attempt_allowed(tournament_id=1, auth_user_id=2)
            self.assertEqual("rate_limit_unavailable", _code(caught.exception))
            # ...and the fail-open side still passes.
            await limits.assert_accept_attempt_allowed(auth_user_id=2)


class InviteCapTests(IsolatedAsyncioTestCase):
    async def test_the_cumulative_cap_exceeds_the_largest_legal_roster(self) -> None:
        """The cap must not be reachable by legitimate use: a 12-slot roster with
        replacements needs far fewer than this."""
        from shared.domain.roster_shape import MAX_TEAM_SIZE

        self.assertGreater(limits.TEAM_INVITE_TOTAL_CAP, MAX_TEAM_SIZE * 2)

    async def test_the_rate_limit_is_looser_than_one_full_roster(self) -> None:
        """A captain must be able to fill a maximum roster inside one window without
        tripping the limiter."""
        from shared.domain.roster_shape import MAX_TEAM_SIZE

        self.assertGreaterEqual(limits.INVITE_ATTEMPT_LIMIT, MAX_TEAM_SIZE)
