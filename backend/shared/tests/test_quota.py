"""The shared quota gate: what it resolves, what it sends to Redis, how it refuses.

Three layers, tested where each one can actually be wrong:

* resolution -- precedence between key, workspace and plan rows, and the one
  irregular rule (counters take the nearest value, per-request caps the
  narrowest);
* the call into Redis -- the key shapes and the limit order the Lua script is
  handed, which is the part a rename silently breaks;
* the verdict -- which HTTP status and which ``limit_name``/``scope`` a refusal
  becomes, and which direction each dimension fails when Redis is gone.

The Lua body itself is exercised against a real server by
``QuotaScriptTests``, skipped unless ``QUOTA_IT_REDIS_URL`` is set.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase

from redis.exceptions import RedisError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.quota.enforcer import CHARGE_SCRIPT, QuotaEnforcer, principal_of  # noqa: E402
from shared.quota.policy import DEFAULT_PLAN_SLUG, PolicyStore, QuotaLimits  # noqa: E402

IT_REDIS_URL = os.environ.get("QUOTA_IT_REDIS_URL")

PLAN = QuotaLimits(
    requests_per_minute=60, heavy_per_day=100, concurrent_heavy=2, max_upload_bytes=10, max_items_per_request=5
)
SESSION_PLAN = QuotaLimits(requests_per_minute=120, heavy_per_day=500, concurrent_heavy=3)
WORKSPACE_PLAN = QuotaLimits(requests_per_minute=600, heavy_per_day=1000, concurrent_heavy=4)


def api_key_user(api_key_id: int = 7, user_id: int = 9) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, _credential_type="api_key", _api_key_id=api_key_id)


def session_user(user_id: int = 9) -> SimpleNamespace:
    return SimpleNamespace(id=user_id, _credential_type="access_token")


class _Policy(PolicyStore):
    """A policy store with the three loads stubbed, so ``resolve`` is the unit."""

    def __init__(
        self,
        *,
        plan: dict[str, QuotaLimits] | None = None,
        workspace_overrides: dict[str, QuotaLimits] | None = None,
        key_override: QuotaLimits = QuotaLimits(),
        costs: dict[str, int] | None = None,
        plan_slug: str | None = "verified",
    ) -> None:
        super().__init__(session_factory=None)
        self._plan = plan or {}
        self._workspace_overrides = workspace_overrides or {}
        self._key_override = key_override
        self._costs = costs or {}
        self._plan_slug = plan_slug

    async def _load_global(self):  # type: ignore[override]
        from shared.quota.policy import _Global

        return _Global(plans={self._plan_slug or "": self._plan}, plan_slugs={}, costs=self._costs)

    async def _load_workspace(self, workspace_id: int):  # type: ignore[override]
        from shared.quota.policy import _WorkspacePolicy

        return _WorkspacePolicy(plan_slug=self._plan_slug, overrides=self._workspace_overrides)

    async def _load_key(self, api_key_id: int) -> QuotaLimits:  # type: ignore[override]
        return self._key_override


class _Script:
    """Stands in for the registered Lua script, recording how it was called."""

    def __init__(self, verdict: list[Any] | None = None, error: Exception | None = None) -> None:
        self.verdict = verdict or [1, "", "", 0, 0]
        self.error = error
        self.keys: list[str] = []
        self.args: list[Any] = []
        self.calls = 0

    async def __call__(self, *, keys: list[str], args: list[Any]) -> list[Any]:
        self.calls += 1
        self.keys, self.args = keys, args
        if self.error is not None:
            raise self.error
        return self.verdict


class _Redis:
    def __init__(self, script: _Script) -> None:
        self.script = script
        self.zrems: list[tuple[str, str]] = []

    def register_script(self, source: str) -> _Script:
        assert source == CHARGE_SCRIPT
        return self.script

    async def zrem(self, key: str, member: str) -> int:
        self.zrems.append((key, member))
        return 1

    async def aclose(self) -> None:
        return None


def enforcer(policy: PolicyStore, script: _Script | None = None, *, enabled: bool = True) -> QuotaEnforcer:
    return QuotaEnforcer(policy=policy, redis_client=_Redis(script or _Script()), enabled=enabled)


class PrincipalTests(unittest.TestCase):
    def test_api_key_and_session_land_in_different_buckets(self) -> None:
        self.assertEqual(("api_key", 7), principal_of(api_key_user()))
        self.assertEqual(("user", 9), principal_of(session_user()))

    def test_a_session_without_an_id_is_not_throttleable(self) -> None:
        self.assertIsNone(principal_of(SimpleNamespace()))

    def test_an_api_key_without_an_id_is_a_broken_credential(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            principal_of(SimpleNamespace(_credential_type="api_key"))
        self.assertEqual(401, caught.exception.status_code)


class ResolutionTests(IsolatedAsyncioTestCase):
    async def test_a_key_override_raises_above_its_plan(self) -> None:
        """Counters take the nearest value set, so a superuser can raise one."""
        policy = _Policy(plan={"key": PLAN}, key_override=QuotaLimits(requests_per_minute=600))
        resolved = await policy.resolve(operation="op", principal_scope="key", api_key_id=7, workspace_id=1)

        self.assertEqual(600, resolved.principal.requests_per_minute)
        # Untouched dimensions still come from the plan.
        self.assertEqual(100, resolved.principal.heavy_per_day)

    async def test_a_workspace_override_sits_between_key_and_plan(self) -> None:
        policy = _Policy(
            plan={"key": PLAN},
            workspace_overrides={"key": QuotaLimits(concurrent_heavy=1, heavy_per_day=50)},
            key_override=QuotaLimits(heavy_per_day=70),
        )
        resolved = await policy.resolve(operation="op", principal_scope="key", api_key_id=7, workspace_id=1)

        self.assertEqual(70, resolved.principal.heavy_per_day)
        self.assertEqual(1, resolved.principal.concurrent_heavy)

    async def test_per_request_caps_take_the_narrowest_level_not_the_nearest(self) -> None:
        """A workspace must be able to tighten uploads without a superuser."""
        policy = _Policy(
            plan={"key": PLAN},
            workspace_overrides={"key": QuotaLimits(max_upload_bytes=4)},
            key_override=QuotaLimits(max_upload_bytes=9),
        )
        resolved = await policy.resolve(operation="op", principal_scope="key", api_key_id=7, workspace_id=1)

        self.assertEqual(4, resolved.principal.max_upload_bytes)

    async def test_the_workspace_scope_is_resolved_for_a_session_principal_too(self) -> None:
        """A member's jobs cost the tenant exactly what a key's do."""
        policy = _Policy(plan={"workspace": WORKSPACE_PLAN, "session": SESSION_PLAN})
        resolved = await policy.resolve(operation="op", principal_scope="session", api_key_id=None, workspace_id=1)

        self.assertEqual(1000, resolved.workspace.heavy_per_day)
        self.assertEqual(500, resolved.principal.heavy_per_day)

    async def test_an_unpriced_operation_costs_nothing(self) -> None:
        policy = _Policy(plan={"key": PLAN}, costs={"balancer.job": 3})
        priced = await policy.resolve(operation="balancer.job", principal_scope="key", api_key_id=7, workspace_id=1)
        free = await policy.resolve(operation="jobs.read", principal_scope="key", api_key_id=7, workspace_id=1)

        self.assertEqual(3, priced.cost)
        self.assertEqual(0, free.cost)

    async def test_no_rows_at_all_means_unlimited(self) -> None:
        resolved = await _Policy().resolve(operation="op", principal_scope="key", api_key_id=7, workspace_id=1)

        self.assertFalse(resolved.principal.counts_anything)
        self.assertFalse(resolved.workspace.counts_anything)

    async def test_a_principal_outside_any_tenant_still_gets_a_plan(self) -> None:
        """The hole a smoke test found: no workspace resolved no plan at all,
        which reads as unlimited. A job poll by id has no workspace to name."""
        policy = _Policy(plan={"key": PLAN}, plan_slug=DEFAULT_PLAN_SLUG)
        resolved = await policy.resolve(operation="op", principal_scope="key", api_key_id=7, workspace_id=None)

        self.assertEqual(60, resolved.principal.requests_per_minute)


class ChargeCallTests(IsolatedAsyncioTestCase):
    async def test_both_scopes_are_sent_with_their_own_limits(self) -> None:
        script = _Script()
        gate = enforcer(
            _Policy(plan={"workspace": WORKSPACE_PLAN, "key": PLAN}, costs={"balancer.job": 3}),
            script,
        )

        await gate.charge(api_key_user(), "balancer.job", workspace_id=42)

        self.assertEqual(
            [
                "q:ws:42:rpm",
                script.keys[1],
                "q:ws:42:heavy:active",
                "q:key:7:rpm",
                script.keys[4],
                "q:key:7:heavy:active",
            ],
            script.keys,
        )
        self.assertTrue(script.keys[1].startswith("q:ws:42:heavy:"))
        self.assertTrue(script.keys[4].startswith("q:key:7:heavy:"))
        # cost, then the workspace triple, then the principal triple.
        self.assertEqual(3, script.args[1])
        self.assertEqual([600, 1000, 4], script.args[7:10])
        self.assertEqual([60, 100, 2], script.args[10:13])
        self.assertEqual(["workspace", "key"], script.args[13:15])

    async def test_a_key_is_charged_to_its_own_tenant_when_the_call_omits_one(self) -> None:
        """A key belongs to one workspace, so a call site that forgets to name
        it must not thereby escape the tenant budget."""
        script = _Script()
        gate = enforcer(_Policy(plan={"workspace": WORKSPACE_PLAN, "key": PLAN}), script)
        user = api_key_user()
        user._api_key_workspace_id = 42

        await gate.charge(user, "balancer.jobs.read")

        self.assertEqual("q:ws:42:rpm", script.keys[0])

    async def test_a_scope_that_bounds_nothing_gets_no_keys(self) -> None:
        """An unconfigured tenant budget must not spawn a counter per minute."""
        script = _Script()
        gate = enforcer(_Policy(plan={"key": PLAN}), script)

        await gate.charge(api_key_user(), "balancer.job", workspace_id=42)

        self.assertEqual(["", "", ""], script.keys[:3])
        self.assertEqual(-1, script.args[7])

    async def test_nothing_is_charged_when_no_scope_is_configured(self) -> None:
        script = _Script()
        gate = enforcer(_Policy(), script)

        await gate.charge(api_key_user(), "balancer.job", workspace_id=42)

        self.assertEqual(0, script.calls)

    async def test_the_kill_switch_short_circuits_before_policy_and_redis(self) -> None:
        script = _Script()
        gate = enforcer(_Policy(plan={"key": PLAN}), script, enabled=False)

        await gate.charge(api_key_user(), "balancer.job", workspace_id=42)

        self.assertEqual(0, script.calls)

    async def test_a_lease_asks_for_a_slot_and_comes_back_addressable(self) -> None:
        script = _Script()
        gate = enforcer(_Policy(plan={"key": PLAN}), script)

        held = await gate.lease(api_key_user(), "balancer.job", ttl_seconds=900, lease_id="job-1", workspace_id=42)

        self.assertEqual(1, script.args[2])
        self.assertEqual("job-1", script.args[3])
        self.assertEqual(900, script.args[4])
        self.assertEqual(("api_key", 7, 42), (held.principal_kind, held.principal_id, held.workspace_id))

    async def test_release_drops_the_member_from_both_scopes(self) -> None:
        gate = enforcer(_Policy(plan={"key": PLAN}))
        held = await gate.lease(api_key_user(), "balancer.job", ttl_seconds=900, lease_id="job-1", workspace_id=42)

        await gate.release(held)

        self.assertEqual(
            [("q:key:7:heavy:active", "job-1"), ("q:ws:42:heavy:active", "job-1")],
            gate._redis.zrems,  # noqa: SLF001 - the fake's recorder is the assertion
        )


class VerdictTests(IsolatedAsyncioTestCase):
    async def test_a_refusal_names_the_dimension_and_the_scope_that_refused(self) -> None:
        script = _Script(verdict=[0, "heavy_per_day", "workspace", 41231, 1000])
        gate = enforcer(_Policy(plan={"workspace": WORKSPACE_PLAN, "key": PLAN}), script)

        with self.assertRaises(HTTPException) as caught:
            await gate.charge(api_key_user(), "balancer.job", workspace_id=42)

        self.assertEqual(429, caught.exception.status_code)
        self.assertEqual(
            {"code": "quota_exceeded", "limit_name": "heavy_per_day", "scope": "workspace", "limit": 1000},
            caught.exception.detail,
        )
        self.assertEqual("41231", caught.exception.headers["Retry-After"])

    async def test_an_oversized_payload_is_refused_before_any_budget_is_spent(self) -> None:
        script = _Script()
        gate = enforcer(_Policy(plan={"key": PLAN}), script)

        with self.assertRaises(HTTPException) as caught:
            await gate.charge(api_key_user(), "balancer.job", workspace_id=42, size_bytes=11)

        self.assertEqual(413, caught.exception.status_code)
        self.assertEqual("quota_payload_too_large", caught.exception.detail["code"])
        self.assertEqual(0, script.calls)

    async def test_too_many_items_is_a_bad_request_not_a_throttle(self) -> None:
        gate = enforcer(_Policy(plan={"key": PLAN}))

        with self.assertRaises(HTTPException) as caught:
            await gate.charge(api_key_user(), "balancer.job", workspace_id=42, item_count=6)

        self.assertEqual(400, caught.exception.status_code)
        self.assertEqual("max_items_per_request", caught.exception.detail["limit_name"])

    async def test_check_payload_settles_caps_without_touching_redis(self) -> None:
        script = _Script()
        gate = enforcer(_Policy(plan={"key": PLAN}), script)

        await gate.check_payload(api_key_user(), "balancer.job", workspace_id=42, size_bytes=10)
        with self.assertRaises(HTTPException):
            await gate.check_payload(api_key_user(), "balancer.job", workspace_id=42, size_bytes=11)

        self.assertEqual(0, script.calls)


class OutageTests(IsolatedAsyncioTestCase):
    async def test_a_counter_fails_open(self) -> None:
        """A lost increment is one over-served request; nginx still caps floods."""
        script = _Script(error=RedisError("down"))
        gate = enforcer(_Policy(plan={"key": PLAN}), script)

        await gate.charge(api_key_user(), "balancer.job", workspace_id=42)

    async def test_a_lease_fails_closed(self) -> None:
        """A slot that cannot be recorded must not be granted: it bounds CPU."""
        script = _Script(error=RedisError("down"))
        gate = enforcer(_Policy(plan={"key": PLAN}), script)

        with self.assertRaises(HTTPException) as caught:
            await gate.lease(api_key_user(), "balancer.job", ttl_seconds=900, workspace_id=42)

        self.assertEqual(503, caught.exception.status_code)
        self.assertEqual("quota_unavailable", caught.exception.detail["code"])


class QuotaScriptTests(IsolatedAsyncioTestCase):
    """The Lua itself: windows, refusal order, atomicity across the two scopes.

    Runs against ``fakeredis``'s script interpreter by default, and against a
    real server when ``QUOTA_IT_REDIS_URL`` is set. The all-or-nothing charge is
    the one thing no stub can vouch for -- it is a property of the script, not
    of the caller.
    """

    async def asyncSetUp(self) -> None:
        if IT_REDIS_URL:
            import redis.asyncio as redis

            self.redis = redis.from_url(IT_REDIS_URL, decode_responses=True)
        else:
            import fakeredis.aioredis as fakeredis

            self.redis = fakeredis.FakeRedis(decode_responses=True)
        self.prefix = f"q:ws:{os.getpid()}"
        await self._flush()

    async def asyncTearDown(self) -> None:
        await self._flush()
        await self.redis.aclose()

    async def _flush(self) -> None:
        for namespace in ("ws", "key"):
            async for key in self.redis.scan_iter(match=f"q:{namespace}:{os.getpid()}*"):
                await self.redis.delete(key)

    def _gate(self, policy: PolicyStore) -> QuotaEnforcer:
        return QuotaEnforcer(policy=policy, redis_client=self.redis)

    async def test_the_window_refuses_the_call_past_the_limit(self) -> None:
        policy = _Policy(plan={"key": QuotaLimits(requests_per_minute=2)}, plan_slug=DEFAULT_PLAN_SLUG)
        gate = self._gate(policy)
        user = api_key_user(api_key_id=os.getpid())

        await gate.charge(user, "op")
        await gate.charge(user, "op")
        with self.assertRaises(HTTPException) as caught:
            await gate.charge(user, "op")

        self.assertEqual("requests_per_minute", caught.exception.detail["limit_name"])
        self.assertEqual("key", caught.exception.detail["scope"])

    async def test_the_tenant_budget_is_not_spent_when_the_key_refuses(self) -> None:
        """All-or-nothing: a retry loop must not drain a pool it never used."""
        policy = _Policy(
            plan={"workspace": QuotaLimits(heavy_per_day=100), "key": QuotaLimits(heavy_per_day=1)},
            costs={"op": 1},
        )
        gate = self._gate(policy)
        user = api_key_user(api_key_id=os.getpid())

        await gate.charge(user, "op", workspace_id=os.getpid())
        for _ in range(3):
            with self.assertRaises(HTTPException):
                await gate.charge(user, "op", workspace_id=os.getpid())

        day_keys = [key async for key in self.redis.scan_iter(match=f"{self.prefix}:heavy:2*")]
        self.assertEqual(["1"], [await self.redis.get(key) for key in day_keys])

    async def test_a_dead_holders_slot_is_pruned_by_the_next_reservation(self) -> None:
        policy = _Policy(plan={"key": QuotaLimits(concurrent_heavy=1)}, plan_slug=DEFAULT_PLAN_SLUG)
        gate = self._gate(policy)
        user = api_key_user(api_key_id=os.getpid())

        await gate.lease(user, "op", ttl_seconds=1, lease_id="dead")
        with self.assertRaises(HTTPException):
            await gate.lease(user, "op", ttl_seconds=60, lease_id="live")

        # Backdate the holder instead of sleeping: expiry is a score, not a TTL.
        await self.redis.zadd(f"q:key:{os.getpid()}:heavy:active", {"dead": 1})
        held = await gate.lease(user, "op", ttl_seconds=60, lease_id="live")

        self.assertEqual("live", held.lease_id)
