"""Per-key quota administration: who may retune a key, and what it reads back.

The authority rule is the whole point here -- a workspace manager may only ever
tighten what the plan and the workspace hand down, while a superuser may widen.
``ensure_can_manage`` is stubbed because it has its own suite next door; what is
exercised is ``allow_raise`` and the fact that both the workspace and the
principal id come off the KEY row rather than off the request.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from shared.models import QuotaApiKeyLimit, QuotaPlanLimit  # noqa: E402
from shared.schemas.quota import QuotaLimitsPayload  # noqa: E402
from src.services import api_keys as api_keys_module  # noqa: E402
from src.services.api_keys import api_keys  # noqa: E402
from tests._fakes import FakeExecuteResult as _FakeExecuteResult  # noqa: E402
from tests._fakes import make_api_key_row as _api_key_row  # noqa: E402
from tests._fakes import make_auth_user as _user  # noqa: E402


class _FakeSession:
    """Serves a queued ``execute`` script; records adds, deletes and commits."""

    def __init__(self, results: list[dict] | None = None) -> None:
        self._results = list(results or [])
        self.added: list[object] = []
        self.deleted: list[object] = []
        self.commit_calls = 0
        self.flush_calls = 0

    def add(self, row: object) -> None:
        self.added.append(row)

    async def delete(self, row: object) -> None:
        self.deleted.append(row)

    async def execute(self, stmt):
        if not self._results:
            raise AssertionError("Unexpected execute() call")
        return _FakeExecuteResult(**self._results.pop(0))

    async def flush(self) -> None:
        # The repositories are transaction-neutral: they flush, the caller
        # commits. A fake without it would pass while the real session broke.
        self.flush_calls += 1

    async def commit(self) -> None:
        self.commit_calls += 1


def _plan_limit(**dims: int | None) -> QuotaPlanLimit:
    return QuotaPlanLimit(scope="key", **dims)


def _inheritance(plan: QuotaPlanLimit, workspace_override: QuotaPlanLimit | None = None) -> list[dict]:
    """The three reads ``inherited_limits`` performs for a ``key``-scope write."""
    return [
        {"first": ("verified", None)},
        {"scalar": plan},
        {"scalar": workspace_override},
    ]


@pytest.fixture
def audit(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Capture the journal entry instead of writing one."""
    entries: list[dict] = []

    async def _record(_session, **kwargs) -> None:
        entries.append(kwargs)

    monkeypatch.setattr(api_keys_module, "record_audit", _record)
    return entries


@pytest.fixture(autouse=True)
def manageable(monkeypatch: pytest.MonkeyPatch):
    """Grant the management gate and serve the key row without a repository."""
    row = _api_key_row()

    async def _allow(*_args, **_kwargs) -> None:
        return None

    class _Keys:
        async def get_with_owner(self, _session, api_key_id: int):
            return row if api_key_id == row.id else None

    monkeypatch.setattr(api_keys, "ensure_can_manage", _allow)
    monkeypatch.setattr(api_keys, "keys", _Keys())
    return row


def _user_superuser():
    user = _user()
    user.is_superuser = True
    return user


def test_workspace_manager_cannot_raise_a_key_above_what_it_inherits(audit: list[dict]) -> None:
    session = _FakeSession(
        [
            {"scalar": None},
            *_inheritance(_plan_limit(requests_per_minute=60, heavy_per_day=100)),
        ]
    )

    with pytest.raises(api_keys_module.HTTPException) as exc_info:
        asyncio.run(
            api_keys.set_quota(
                session,
                user=_user(),
                api_key_id=123,
                limits=QuotaLimitsPayload(heavy_per_day=5000),
            )
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "quota_above_inherited"
    assert exc_info.value.detail["limit_name"] == "heavy_per_day"
    assert exc_info.value.detail["limit"] == 100
    assert exc_info.value.detail["requested"] == 5000
    assert session.commit_calls == 0
    assert audit == []


def test_workspace_manager_may_lower_a_key_below_what_it_inherits(audit: list[dict]) -> None:
    session = _FakeSession(
        [
            {"scalar": None},
            *_inheritance(_plan_limit(requests_per_minute=60, heavy_per_day=100)),
            {"scalar": None},
        ]
    )

    result = asyncio.run(
        api_keys.set_quota(
            session,
            user=_user(),
            api_key_id=123,
            limits=QuotaLimitsPayload(heavy_per_day=10),
        )
    )

    assert result.heavy_per_day == 10
    assert session.added[0].heavy_per_day == 10
    assert session.commit_calls == 1


def test_superuser_may_raise_a_key_above_what_it_inherits(audit: list[dict]) -> None:
    """``allow_raise`` skips the inheritance read entirely, hence the short script."""
    session = _FakeSession([{"scalar": None}, {"scalar": None}])

    result = asyncio.run(
        api_keys.set_quota(
            session,
            user=_user_superuser(),
            api_key_id=123,
            limits=QuotaLimitsPayload(heavy_per_day=5000),
        )
    )

    assert result.heavy_per_day == 5000
    stored = session.added[0]
    assert isinstance(stored, QuotaApiKeyLimit)
    assert stored.api_key_id == 123
    assert stored.heavy_per_day == 5000
    assert stored.updated_by == 7
    assert session.commit_calls == 1


def test_setting_every_dimension_to_null_drops_the_override(audit: list[dict]) -> None:
    """An all-null payload is "inherit again", not five explicit nulls."""
    existing = QuotaApiKeyLimit(api_key_id=123, heavy_per_day=10)
    session = _FakeSession([{"scalar": existing}, {"scalar": existing}])

    asyncio.run(
        api_keys.set_quota(
            session,
            user=_user_superuser(),
            api_key_id=123,
            limits=QuotaLimitsPayload(),
        )
    )

    assert session.deleted == [existing]
    assert session.added == []
    assert session.commit_calls == 1


def test_quota_write_is_journalled_with_the_previous_and_new_limits(audit: list[dict]) -> None:
    session = _FakeSession(
        [
            {"scalar": QuotaApiKeyLimit(api_key_id=123, heavy_per_day=10)},
            {"scalar": None},
        ]
    )

    asyncio.run(
        api_keys.set_quota(
            session,
            user=_user_superuser(),
            api_key_id=123,
            limits=QuotaLimitsPayload(heavy_per_day=25),
        )
    )

    entry = audit[0]
    assert entry["action"] == "api_key.quota_update"
    assert entry["entity_type"] == "api_key"
    assert entry["entity_id"] == 123
    assert entry["workspace_id"] == 11
    assert entry["before"]["heavy_per_day"] == 10
    assert entry["after"]["heavy_per_day"] == 25


def test_usage_read_reports_the_plan_and_one_entry_per_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _FakeSession([{"first": ("verified", None)}])
    seen: dict[str, object] = {}

    async def _usage(*, principal_kind: str, principal_id: int, workspace_id: int | None):
        seen.update(principal_kind=principal_kind, principal_id=principal_id, workspace_id=workspace_id)
        return {
            "workspace_id": workspace_id,
            "scopes": [
                {"scope": "workspace", "requests_per_minute": 600, "requests_used": 12},
                {"scope": "key", "requests_per_minute": 60, "requests_used": 12},
            ],
        }

    monkeypatch.setattr(api_keys_module.quota, "usage", _usage)

    result = asyncio.run(api_keys.quota_usage(session, user=_user(), api_key_id=123))

    # The workspace is the key's own, never one the caller could name.
    assert seen == {"principal_kind": "api_key", "principal_id": 123, "workspace_id": 11}
    assert result.plan_slug == "verified"
    assert result.workspace_id == 11
    assert [scope.scope for scope in result.scopes] == ["workspace", "key"]
    assert [scope.requests_per_minute for scope in result.scopes] == [600, 60]


def test_a_key_reads_its_own_budget_without_the_management_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """The self read must work for a key whose holder is nobody's workspace admin."""
    session = _FakeSession([{"first": ("verified", None)}])

    async def _deny(*_args, **_kwargs) -> None:
        raise AssertionError("self_quota_usage must not consult the management gate")

    async def _usage(*, principal_kind: str, principal_id: int, workspace_id: int | None):
        return {"workspace_id": workspace_id, "scopes": [{"scope": "key", "requests_per_minute": 60}]}

    monkeypatch.setattr(api_keys, "ensure_can_manage", _deny)
    monkeypatch.setattr(api_keys_module.quota, "usage", _usage)

    result = asyncio.run(api_keys.self_quota_usage(session, api_key_id=123))

    assert [scope.scope for scope in result.scopes] == ["key"]
    assert result.plan_slug == "verified"
