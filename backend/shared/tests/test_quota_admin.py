"""The one rule the quota admin layer exists to enforce, against real SQL.

A superuser may raise a limit; a workspace admin may only lower it. That is
checked once, on the way in, so the stored row is always the truth and a read
never has to second-guess it -- which makes the check itself the thing worth
pinning, and pinning it against emitted SQL rather than a mocked session,
because "what does this workspace inherit" is a property of three joined tables.

SQLite stands in for Postgres (the repo's usual arrangement: schemas are
ATTACHed, `install_postgres_type_shims` degrades the Postgres types, and a
synchronous ``Session`` behind an async facade avoids needing aiosqlite).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from unittest import TestCase

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("DEBUG", "false")

from shared.core.errors import BaseAPIException as HTTPException  # noqa: E402
from shared.models import (  # noqa: E402
    QuotaApiKeyLimit,
    QuotaOperation,
    QuotaPlan,
    QuotaPlanLimit,
    QuotaWorkspaceLimit,
    Workspace,
)
from shared.quota import admin as quota_admin  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402

install_postgres_type_shims()

WORKSPACE_ID = 42
API_KEY_ID = 7
PLAN_KEY_LIMITS = {
    "requests_per_minute": 60,
    "heavy_per_day": 100,
    "concurrent_heavy": 2,
    "max_upload_bytes": 10485760,
    "max_items_per_request": 500,
}


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session``: no aiosqlite is installed,
    and the admin helpers await only ``execute``, ``flush``, ``delete``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        return self._session.execute(*args, **kwargs)

    async def flush(self) -> None:
        self._session.flush()

    async def delete(self, instance) -> None:  # noqa: ANN001
        self._session.delete(instance)

    def add(self, instance) -> None:  # noqa: ANN001
        self._session.add(instance)


class QuotaAdminTests(TestCase):
    def setUp(self) -> None:
        tables = [
            Workspace.__table__,
            QuotaPlan.__table__,
            QuotaPlanLimit.__table__,
            QuotaOperation.__table__,
            QuotaWorkspaceLimit.__table__,
            QuotaApiKeyLimit.__table__,
        ]
        self.engine = sa.create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in tables if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in tables:
                table.create(conn)

        self.sync_session = Session(self.engine)
        self.addCleanup(self.sync_session.close)
        self.session = _AsyncSessionShim(self.sync_session)

        self.sync_session.execute(
            sa.insert(Workspace.__table__).values(
                id=WORKSPACE_ID,
                slug="acme",
                name="Acme",
                verification_status="verified",
            )
        )
        self.sync_session.execute(sa.insert(QuotaPlan.__table__).values(id=1, slug="verified", title="Verified"))
        self.sync_session.execute(sa.insert(QuotaPlanLimit.__table__).values(plan_id=1, scope="key", **PLAN_KEY_LIMITS))
        self.sync_session.commit()

    def _run(self, coro):  # noqa: ANN001, ANN202
        return asyncio.run(coro)

    def _limits(self, **overrides: int | None) -> dict[str, int | None]:
        values = dict.fromkeys(quota_admin.DIMENSIONS)
        values.update(overrides)
        return values

    def test_a_workspace_admin_may_lower_a_key_limit(self) -> None:
        self._run(
            quota_admin.apply_api_key_limits(
                self.session,
                api_key_id=API_KEY_ID,
                workspace_id=WORKSPACE_ID,
                values=self._limits(requests_per_minute=30),
                updated_by=9,
                allow_raise=False,
            )
        )
        self.sync_session.commit()

        stored = self.sync_session.execute(sa.select(QuotaApiKeyLimit.__table__)).mappings().one()
        self.assertEqual(30, stored["requests_per_minute"])
        self.assertIsNone(stored["heavy_per_day"], "an omitted dimension stays inherited, not zeroed")
        self.assertEqual(9, stored["updated_by"])

    def test_a_workspace_admin_may_not_raise_above_the_plan(self) -> None:
        with self.assertRaises(HTTPException) as caught:
            self._run(
                quota_admin.apply_api_key_limits(
                    self.session,
                    api_key_id=API_KEY_ID,
                    workspace_id=WORKSPACE_ID,
                    values=self._limits(requests_per_minute=600),
                    updated_by=9,
                    allow_raise=False,
                )
            )

        self.assertEqual(422, caught.exception.status_code)
        self.assertEqual("quota_above_inherited", caught.exception.detail["code"])
        self.assertEqual("requests_per_minute", caught.exception.detail["limit_name"])
        self.assertEqual(60, caught.exception.detail["limit"])
        self.assertEqual(600, caught.exception.detail["requested"])

    def test_a_superuser_may_raise_above_the_plan(self) -> None:
        """The escape hatch: a partner integration without moving a whole tier."""
        self._run(
            quota_admin.apply_api_key_limits(
                self.session,
                api_key_id=API_KEY_ID,
                workspace_id=WORKSPACE_ID,
                values=self._limits(requests_per_minute=600),
                updated_by=1,
                allow_raise=True,
            )
        )
        self.sync_session.commit()

        stored = self.sync_session.execute(sa.select(QuotaApiKeyLimit.__table__)).mappings().one()
        self.assertEqual(600, stored["requests_per_minute"])

    def test_a_tenant_tightening_its_keys_cannot_be_widened_by_one_of_them(self) -> None:
        """A key write inherits through the workspace override, not around it."""
        self._run(
            quota_admin.apply_workspace_limits(
                self.session,
                workspace_id=WORKSPACE_ID,
                scope="key",
                values=self._limits(requests_per_minute=20),
                updated_by=1,
                allow_raise=False,
            )
        )
        self.sync_session.commit()

        with self.assertRaises(HTTPException) as caught:
            self._run(
                quota_admin.apply_api_key_limits(
                    self.session,
                    api_key_id=API_KEY_ID,
                    workspace_id=WORKSPACE_ID,
                    values=self._limits(requests_per_minute=50),
                    updated_by=9,
                    allow_raise=False,
                )
            )

        self.assertEqual(20, caught.exception.detail["limit"])

    def test_an_unset_dimension_is_unlimited_and_may_be_lowered(self) -> None:
        """The plan sets no workspace-scope row, so the tenant budget is
        unlimited -- and a workspace admin capping it is the point."""
        self._run(
            quota_admin.apply_workspace_limits(
                self.session,
                workspace_id=WORKSPACE_ID,
                scope="workspace",
                values=self._limits(heavy_per_day=1000),
                updated_by=9,
                allow_raise=False,
            )
        )
        self.sync_session.commit()

        stored = (
            self.sync_session.execute(
                sa.select(QuotaWorkspaceLimit.__table__).where(QuotaWorkspaceLimit.__table__.c.scope == "workspace")
            )
            .mappings()
            .one()
        )
        self.assertEqual(1000, stored["heavy_per_day"])

    def test_an_all_null_payload_drops_the_override(self) -> None:
        self._run(
            quota_admin.apply_api_key_limits(
                self.session,
                api_key_id=API_KEY_ID,
                workspace_id=WORKSPACE_ID,
                values=self._limits(requests_per_minute=30),
                updated_by=9,
                allow_raise=False,
            )
        )
        self.sync_session.commit()

        self._run(
            quota_admin.apply_api_key_limits(
                self.session,
                api_key_id=API_KEY_ID,
                workspace_id=WORKSPACE_ID,
                values=self._limits(),
                updated_by=9,
                allow_raise=False,
            )
        )
        self.sync_session.commit()

        self.assertEqual([], self.sync_session.execute(sa.select(QuotaApiKeyLimit.__table__)).mappings().all())

    def test_the_plan_comes_from_an_explicit_assignment_before_the_tier(self) -> None:
        self.sync_session.execute(sa.insert(QuotaPlan.__table__).values(id=2, slug="partner-esl", title="Partner"))
        self.sync_session.execute(
            sa.update(Workspace.__table__).where(Workspace.__table__.c.id == WORKSPACE_ID).values(quota_plan_id=2)
        )
        self.sync_session.commit()

        self.assertEqual("partner-esl", self._run(quota_admin.plan_slug_for_workspace(self.session, WORKSPACE_ID)))

    def test_replacing_a_plan_replaces_its_scope_rows_wholesale(self) -> None:
        """A plan is read as a complete statement of its tier: a partial update
        would leave a scope nobody remembers setting."""
        self._run(
            quota_admin.upsert_plan(
                self.session,
                slug="verified",
                title="Verified",
                description=None,
                limits=[{"scope": "session", "requests_per_minute": 120}],
            )
        )
        self.sync_session.commit()

        rows = self.sync_session.execute(sa.select(QuotaPlanLimit.__table__)).mappings().all()
        self.assertEqual(["session"], [row["scope"] for row in rows])
        self.assertEqual(120, rows[0]["requests_per_minute"])
