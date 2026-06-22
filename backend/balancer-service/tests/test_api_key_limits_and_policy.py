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

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("CHALLONGE_USERNAME", "test")
os.environ.setdefault("CHALLONGE_API_KEY", "test")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")
os.environ["DEBUG"] = "false"

from src.core import auth as auth_dependencies  # noqa: E402
from src.core.security.api_key_limiter import ApiKeyUsageLimiter  # noqa: E402
from src.core.security.api_key_policy import validate_api_key_config_policy  # noqa: E402
from src.core.security.workspace_access import WorkspaceAccessPolicy  # noqa: E402


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.active_sets: dict[str, set[str]] = {}

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
        "_api_key_scopes": ["balancer.jobs"],
        "_api_key_limits": {
            "requests_per_minute": 60,
            "jobs_per_day": 100,
            "concurrent_jobs": 2,
            "max_upload_bytes": 10 * 1024 * 1024,
            "max_players": 500,
        },
        "_api_key_config_policy": {},
    }
    values.update(overrides)
    return SimpleNamespace(
        **values,
        has_workspace_permission=lambda workspace_id, resource, action: workspace_id == 11
        and resource == "team"
        and action == "import",
    )


def _limiter(fake_redis: FakeRedis) -> ApiKeyUsageLimiter:
    limiter = ApiKeyUsageLimiter.__new__(ApiKeyUsageLimiter)
    limiter._redis = fake_redis
    return limiter


def test_config_policy_rejects_disallowed_field() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_api_key_config_policy(_api_key_user(), {"solver": "expensive"})

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "api_key_config_field_not_allowed"
    assert exc_info.value.detail["field"] == "solver"


def test_config_policy_rejects_expensive_caps() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_api_key_config_policy(_api_key_user(), {"population_size": 151})

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == {
        "code": "api_key_config_value_too_high",
        "field": "population_size",
        "max": 150,
    }


def test_config_policy_rejects_algorithm_override_field() -> None:
    with pytest.raises(HTTPException) as exc_info:
        validate_api_key_config_policy(_api_key_user(), {"algorithm": "cpsat"})

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail["code"] == "api_key_config_field_not_allowed"
    assert exc_info.value.detail["field"] == "algorithm"


def test_limiter_returns_429_with_retry_after_for_request_limit() -> None:
    user = _api_key_user(_api_key_limits={"requests_per_minute": 1})
    limiter = _limiter(FakeRedis())

    asyncio.run(limiter.check_request(user))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(limiter.check_request(user))

    assert exc_info.value.status_code == 429
    assert exc_info.value.headers["Retry-After"] == "60"
    assert exc_info.value.detail == "API key limit exceeded: requests_per_minute"


def test_limiter_enforces_concurrent_jobs_and_releases_active_job() -> None:
    redis = FakeRedis()
    user = _api_key_user(_api_key_limits={"concurrent_jobs": 1, "jobs_per_day": 10})
    limiter = _limiter(redis)

    asyncio.run(limiter.reserve_job(user, "job-1"))
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(limiter.reserve_job(user, "job-2"))
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "API key limit exceeded: concurrent_jobs"

    asyncio.run(limiter.release_job(42, "job-1"))
    asyncio.run(limiter.reserve_job(user, "job-2"))
    assert "job-2" in redis.active_sets[limiter.active_jobs_key(42)]


def test_limiter_enforces_jobs_per_day_after_release() -> None:
    user = _api_key_user(_api_key_limits={"concurrent_jobs": 2, "jobs_per_day": 1})
    limiter = _limiter(FakeRedis())

    asyncio.run(limiter.reserve_job(user, "job-1"))
    asyncio.run(limiter.release_job(42, "job-1"))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(limiter.reserve_job(user, "job-2"))

    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == "API key limit exceeded: jobs_per_day"


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


def test_admin_workspace_dependencies_reject_api_key_principals() -> None:
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_dependencies._require_workspace_permission(
                _api_key_user(),
                workspace_id=11,
                resource="team",
                action="import",
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "API keys cannot access balancer admin endpoints"
