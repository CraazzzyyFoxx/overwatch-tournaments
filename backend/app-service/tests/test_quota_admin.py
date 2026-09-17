"""The authority rule on ``rpc.app.workspaces.quota_set``.

§4.8 of the rate-limit design: a superuser may raise or lower any dimension, a
workspace admin may only lower one below what the plan grants. That asymmetry is
the whole point of the endpoint -- both writers pass the same
``workspace.update`` gate, so if ``allow_raise`` is ever wired to something other
than ``user.is_superuser`` the permission check stays green while a tenant
quietly grants itself the platform's budget.

The real ``shared.quota.admin`` runs here against a fake session; only the
permission gate and the workspace lookup are stubbed. Routing by the compiled
SQL keeps the fake honest about which table each read hits -- and the
workspace-limit read answers with the row the write just added, the way
autoflush would, so the effective-limits response is a real merge rather than an
echo of the plan.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from shared.models import QuotaPlanLimit, QuotaWorkspaceLimit
from shared.models.platform.audit import AuditLog
from src.rpc import workspaces as workspaces_rpc
from tests.test_audit_workspace import _handler, _workspace

_WORKSPACE_ID = 7
_ADMIN = {"user_id": 42, "username": "kate", "is_active": True, "is_superuser": False}
_SUPERUSER = {"user_id": 1, "username": "root", "is_active": True, "is_superuser": True}

_QUOTA_SUBJECTS = (
    "rpc.app.workspaces.quota_set",
    "rpc.app.quota.plans",
    "rpc.app.quota.plan_upsert",
    "rpc.app.quota.operations",
    "rpc.app.quota.operation_upsert",
    "rpc.app.quota.workspace_usage",
)


class _Result:
    """The two read shapes the code under test uses: a bare scalar/row tuple,
    and ``unique().scalars().first()``, which is how ``BaseRepository`` reads."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def first(self) -> Any:
        return self._value

    def unique(self) -> _Result:
        return self

    def scalars(self) -> SimpleNamespace:
        return SimpleNamespace(first=lambda: self._value, all=lambda: [self._value] if self._value else [])


class _QuotaSession:
    """Answers each read by the table it names, and records the write order."""

    def __init__(self, *, plan_limit: QuotaPlanLimit | None, override: QuotaWorkspaceLimit | None = None) -> None:
        self.plan_limit = plan_limit
        self.override = override
        self.events: list[str] = []
        self.added: list[Any] = []
        self.deleted: list[Any] = []

    async def execute(self, statement: Any) -> _Result:
        sql = str(statement)
        if "quota.plan_limit" in sql:
            return _Result(self.plan_limit)
        if "quota.workspace_limit" in sql:
            return _Result(self._current_override())
        # Everything left is ``plan_slug_for_workspace`` reading the workspace's
        # tier; no explicit plan id, so the tier names the plan.
        return _Result(("verified", None))

    def _current_override(self) -> QuotaWorkspaceLimit | None:
        """What a re-read sees: the row this call wrote, or deleted, or neither."""
        written = [obj for obj in self.added if isinstance(obj, QuotaWorkspaceLimit)]
        if written:
            return written[-1]
        return None if self.override in self.deleted else self.override

    def add(self, obj: Any) -> None:
        self.events.append("add")
        self.added.append(obj)

    async def delete(self, obj: Any) -> None:
        self.events.append("delete")
        self.deleted.append(obj)

    async def flush(self) -> None:
        self.events.append("flush")

    async def commit(self) -> None:
        self.events.append("commit")

    async def rollback(self) -> None:
        self.events.append("rollback")

    async def __aenter__(self) -> _QuotaSession:
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    @property
    def audit_rows(self) -> list[AuditLog]:
        return [obj for obj in self.added if isinstance(obj, AuditLog)]


def _plan_limit(**values: int | None) -> QuotaPlanLimit:
    return QuotaPlanLimit(plan_id=1, scope="workspace", **values)


class QuotaSetAuthorityTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        # The gate has its own coverage on the neighbouring writes; here it must
        # pass so both actors reach the authority rule, which is what differs.
        patcher = patch.object(workspaces_rpc, "ensure_workspace_permission", MagicMock())
        patcher.start()
        self.addCleanup(patcher.stop)

    async def _call(self, identity: dict, limits: dict, *, session: _QuotaSession) -> dict:
        handler = _handler(workspaces_rpc, "rpc.app.workspaces.quota_set")
        with (
            patch.object(workspaces_rpc, "_SF", lambda: session),
            patch.object(workspaces_rpc.workspace_service, "get_by_id", AsyncMock(return_value=_workspace())),
        ):
            return await handler(
                {
                    "workspace_id": _WORKSPACE_ID,
                    "identity": identity,
                    "payload": {"scope": "workspace", "limits": limits},
                },
                MagicMock(),
            )

    async def test_a_workspace_admin_may_lower_below_the_plan(self) -> None:
        session = _QuotaSession(plan_limit=_plan_limit(requests_per_minute=600, heavy_per_day=100))

        envelope = await self._call(_ADMIN, {"heavy_per_day": 10}, session=session)

        self.assertEqual(10, envelope["data"]["heavy_per_day"])
        # Untouched dimensions keep inheriting the plan: the answer is the
        # effective ceiling, not the row that was written.
        self.assertEqual(600, envelope["data"]["requests_per_minute"])
        self.assertEqual("workspace", envelope["data"]["scope"])
        self.assertEqual(10, session.added[0].heavy_per_day)
        self.assertEqual(_ADMIN["user_id"], session.added[0].updated_by)

    async def test_a_workspace_admin_may_not_raise_above_the_plan(self) -> None:
        session = _QuotaSession(plan_limit=_plan_limit(requests_per_minute=600, heavy_per_day=100))

        envelope = await self._call(_ADMIN, {"heavy_per_day": 5000}, session=session)

        self.assertEqual("unprocessable", envelope["error"]["code"])
        # The code and the offending dimension ride ``details``; the message is
        # prose and nothing may branch on it.
        refusal = envelope["error"]["details"]["fields"][0]
        self.assertEqual("quota_above_inherited", refusal["code"])
        self.assertEqual("heavy_per_day", refusal["limit_name"])
        self.assertEqual(100, refusal["limit"])
        self.assertEqual(5000, refusal["requested"])
        # Refused before anything was written, and before any audit row claimed
        # the write happened.
        self.assertEqual([], session.events)
        self.assertEqual([], session.audit_rows)

    async def test_a_superuser_may_raise_above_the_plan(self) -> None:
        session = _QuotaSession(plan_limit=_plan_limit(requests_per_minute=600, heavy_per_day=100))

        envelope = await self._call(_SUPERUSER, {"heavy_per_day": 5000}, session=session)

        self.assertEqual(5000, envelope["data"]["heavy_per_day"])
        self.assertEqual(5000, session.added[0].heavy_per_day)

    async def test_the_write_is_audited_inside_its_own_transaction(self) -> None:
        override = QuotaWorkspaceLimit(workspace_id=_WORKSPACE_ID, scope="workspace", heavy_per_day=50)
        session = _QuotaSession(plan_limit=_plan_limit(heavy_per_day=100), override=override)

        envelope = await self._call(_ADMIN, {"heavy_per_day": 20}, session=session)

        self.assertIn("data", envelope)
        rows = session.audit_rows
        self.assertEqual(1, len(rows))
        self.assertEqual("workspace.quota_update", rows[0].action)
        self.assertEqual(_WORKSPACE_ID, rows[0].workspace_id)
        self.assertEqual("workspace", rows[0].entity_type)
        self.assertEqual(50, rows[0].before_json["heavy_per_day"])
        self.assertEqual(20, rows[0].after_json["heavy_per_day"])
        # Staged before the commit, or a rolled-back write keeps a trail of
        # having happened.
        self.assertEqual("commit", session.events[-1])
        self.assertLess(session.events.index("add"), session.events.index("commit"))

    async def test_an_all_null_payload_drops_the_override(self) -> None:
        """Back onto the plan, rather than five pinned nulls."""
        override = QuotaWorkspaceLimit(workspace_id=_WORKSPACE_ID, scope="workspace", heavy_per_day=50)
        session = _QuotaSession(plan_limit=_plan_limit(heavy_per_day=100), override=override)

        envelope = await self._call(_ADMIN, {}, session=session)

        self.assertEqual([override], session.deleted)
        self.assertEqual(100, envelope["data"]["heavy_per_day"])
        self.assertIsNone(session.audit_rows[0].after_json)


class ManifestTests(IsolatedAsyncioTestCase):
    """Every new subject registered, documented and typed: an unregistered one
    is only visible as a gateway timeout, and one missing from ``OPERATIONS``
    degrades to a generic ``object`` in the published manifest."""

    def test_registered_documented_and_typed(self) -> None:
        from src import openapi_docs, openapi_schemas

        registered: dict[str, object] = {}

        def subscriber(name, *args, **kwargs):
            def decorator(fn):
                registered[name] = fn
                return fn

            return decorator

        broker = MagicMock()
        broker.subscriber = subscriber
        for module in ("src.rpc.workspaces", "src.rpc.quota"):
            importlib.import_module(module).register(broker, MagicMock())

        for subject in _QUOTA_SUBJECTS:
            with self.subTest(subject=subject):
                self.assertIn(subject, registered)
                self.assertTrue(openapi_docs.DOCS[subject]["summary"])
                self.assertIn(subject, openapi_schemas.OPERATIONS)

    def test_the_quota_docs_name_the_429_contract(self) -> None:
        """The rejection shape is the only thing a client can branch on, so it
        has to be in the published description, not just in the code."""
        from src import openapi_docs

        for subject in _QUOTA_SUBJECTS:
            with self.subTest(subject=subject):
                description = openapi_docs.DOCS[subject]["description"]
                self.assertIn("code=rate_limited", description)
                self.assertIn("details.limit_name", description)
                self.assertIn("details.scope", description)
