from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.core.errors import BaseAPIException as HTTPException

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
BALANCER_SERVICE_ROOT = REPO_BACKEND_ROOT / "balancer-service"

for candidate in (str(REPO_BACKEND_ROOT), str(BALANCER_SERVICE_ROOT)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

os.environ["DEBUG"] = "false"

from src.core.security.api_key_limiter import (  # noqa: E402
    REQUEST_SCRIPT,
    RESERVE_JOB_SCRIPT,
    ApiKeyUsageLimiter,
)
from src.core.security.workspace_access import WorkspaceAccessPolicy  # noqa: E402
from src.rpc import _common as rpc_common  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.active_sets: dict[str, set[str]] = {}

    def register_script(self, script):
        async def run(keys=(), args=(), client=None):
            return await self.eval(script, len(keys), *keys, *args)

        return run

    async def eval(self, _script, numkeys, *args):
        if numkeys == 1:
            key, request_limit, retry_after = args
            current = self.values.get(key, 0) + 1
            self.values[key] = current
            if current > int(request_limit):
                return [0, int(retry_after)]
            return [1, 0]

        daily_key, active_key, jobs_limit, daily_retry_after, concurrent_limit, job_id, _active_ttl = args
        active = self.active_sets.setdefault(active_key, set())
        if len(active) >= int(concurrent_limit):
            return [0, 30, "concurrent_jobs"]

        current = self.values.get(daily_key, 0) + 1
        self.values[daily_key] = current
        if current > int(jobs_limit):
            return [0, int(daily_retry_after), "jobs_per_day"]

        active.add(str(job_id))
        return [1, 0, "ok"]

    async def srem(self, key, value):
        self.active_sets.setdefault(key, set()).discard(str(value))
        return 1

    async def aclose(self) -> None:
        return None


def _api_key_user(**overrides):
    values = {
        "_credential_type": "api_key",
        "_api_key_id": 42,
        "_api_key_workspace_id": 11,
        # Scopes reaching the balancer are already-normalized catalog permission
        # names: identity-service expands the legacy "balancer.jobs" alias into
        # team.create before it ever signs a payload.
        "_api_key_scopes": ["team.create"],
        "_api_key_limits": {
            "requests_per_minute": 60,
            "jobs_per_day": 100,
            "concurrent_jobs": 2,
            "max_upload_bytes": 10 * 1024 * 1024,
            "max_players": 500,
        },
    }
    values.update(overrides)
    return SimpleNamespace(
        **values,
        # Mirrors the grant validate_api_key puts on a real key: team.create,
        # which is what every balancer job path checks.
        has_workspace_permission=lambda workspace_id, resource, action: workspace_id == 11
        and resource == "team"
        and action == "create",
    )


def _limiter(fake_redis: FakeRedis) -> ApiKeyUsageLimiter:
    limiter = ApiKeyUsageLimiter.__new__(ApiKeyUsageLimiter)
    limiter._redis = fake_redis
    limiter._request_script = fake_redis.register_script(REQUEST_SCRIPT)
    limiter._reserve_job_script = fake_redis.register_script(RESERVE_JOB_SCRIPT)
    return limiter


def test_limiter_returns_429_with_retry_after_for_request_limit() -> None:
    user = _api_key_user(_api_key_limits={"requests_per_minute": 1})
    limiter = _limiter(FakeRedis())

    asyncio.run(limiter.check_request(user))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(limiter.check_request(user))

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "60"
    assert exc_info.value.detail == "Balancer rate limit exceeded: requests_per_minute"


def test_limiter_enforces_concurrent_jobs_and_releases_active_job() -> None:
    redis = FakeRedis()
    user = _api_key_user(_api_key_limits={"concurrent_jobs": 1, "jobs_per_day": 10})
    limiter = _limiter(redis)

    asyncio.run(limiter.reserve_job(user, "job-1"))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(limiter.reserve_job(user, "job-2"))
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Balancer rate limit exceeded: concurrent_jobs"

    asyncio.run(limiter.release_job("api_key", 42, "job-1"))
    asyncio.run(limiter.reserve_job(user, "job-2"))
    assert "job-2" in redis.active_sets[limiter.active_jobs_key("api_key", 42)]


def test_limiter_enforces_jobs_per_day_after_release() -> None:
    user = _api_key_user(_api_key_limits={"concurrent_jobs": 2, "jobs_per_day": 1})
    limiter = _limiter(FakeRedis())

    asyncio.run(limiter.reserve_job(user, "job-1"))
    asyncio.run(limiter.release_job("api_key", 42, "job-1"))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(limiter.reserve_job(user, "job-2"))

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "Balancer rate limit exceeded: jobs_per_day"


def test_limiter_applies_session_limits_to_non_api_key_principals() -> None:
    """Session (non-API-key) users are now bucketed and capped too (review H5)."""
    redis = FakeRedis()
    session_user = SimpleNamespace(id=777, _credential_type="access_token")
    limiter = _limiter(redis)

    # Concurrency is bucketed under balancer:user:{id}:active_jobs.
    asyncio.run(limiter.reserve_job(session_user, "job-a"))
    assert "job-a" in redis.active_sets[limiter.active_jobs_key("user", 777)]

    asyncio.run(limiter.release_job("user", 777, "job-a"))
    assert "job-a" not in redis.active_sets[limiter.active_jobs_key("user", 777)]


def test_workspace_policy_limits_api_key_to_own_workspace_and_jobs() -> None:
    policy = WorkspaceAccessPolicy()
    user = _api_key_user()

    policy.ensure_workspace_access(user, 11, api_key_id=42, require_api_key_job_match=True)

    with pytest.raises(HTTPException) as exc_info:
        policy.ensure_workspace_access(user, 11, api_key_id=99, require_api_key_job_match=True)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "API key cannot access jobs created by another key"

    with pytest.raises(HTTPException) as exc_info:
        policy.ensure_workspace_access(user, 12, api_key_id=42, require_api_key_job_match=True)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "API key is not scoped to this workspace"


def test_workspace_policy_requires_team_create_scope() -> None:
    """A key whose scopes do not cover team.create cannot touch the job API.

    The owner still holds team.create here (the fixture's RBAC says so), so this
    proves the scope gate is a real floor and not a restatement of RBAC.
    """
    policy = WorkspaceAccessPolicy()
    user = _api_key_user(_api_key_scopes=["registration.approve"])

    with pytest.raises(HTTPException) as exc_info:
        policy.ensure_workspace_access(user, 11, api_key_id=42, require_api_key_job_match=True)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "API key scope required: team.create"


def test_workspace_policy_accepts_admin_wildcard_scope() -> None:
    """``admin.*`` is the catalog's ("*", "*") entry, so it covers team.create."""
    policy = WorkspaceAccessPolicy()
    user = _api_key_user(_api_key_scopes=["admin.*"])

    policy.ensure_workspace_access(user, 11, api_key_id=42, require_api_key_job_match=True)


def test_workspace_policy_rejects_empty_scopes() -> None:
    """An unscoped key grants nothing -- there is no implicit default scope."""
    policy = WorkspaceAccessPolicy()
    user = _api_key_user(_api_key_scopes=[])

    with pytest.raises(HTTPException) as exc_info:
        policy.ensure_workspace_access(user, 11, api_key_id=42)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "API key scope required: team.create"


def test_admin_gate_authorizes_api_key_by_workspace_rbac() -> None:
    """Balancer admin RPC no longer blanket-rejects API keys.

    Identity-service already intersected the key's scopes with its owner's rights
    in the key's single workspace, so ``rbac_permissions`` are authoritative and
    the gate is plain workspace RBAC -- credential type is not consulted.
    """
    api_key_data = {"identity": {"credential_type": "api_key"}}
    user = _api_key_user()

    rpc_common.require_workspace_permission(api_key_data, user, 11, "team", "create")

    # Still bounded by what the payload actually grants: another workspace, and
    # a permission the key does not carry, both stay 403.
    with pytest.raises(HTTPException) as exc_info:
        rpc_common.require_workspace_permission(api_key_data, user, 12, "team", "create")
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        rpc_common.require_workspace_permission(api_key_data, user, 11, "workspace", "update")
    assert exc_info.value.status_code == 403
