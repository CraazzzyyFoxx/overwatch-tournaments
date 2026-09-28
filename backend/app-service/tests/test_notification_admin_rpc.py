"""Behavioural pins for the workspace notification operator screen.

``rpc.app.notification_admin_*`` is the one surface where an operator acts on
rows addressed to *other people*, so the three things it must never get wrong
are all cross-tenant or cross-audience:

* the scope is ``source_workspace_id`` -- the tenant that produced the row --
  and a neighbouring workspace's notifications must be neither listed nor
  retirable, no matter which ids are named;
* announcements stay out: they have their own CRUD, their own locale rules and
  their own permission, and one row must not have two delete buttons;
* "delete" is a retire. The row and its read marks survive, because
  ``notification_read`` points at the id with no foreign key and the inbox has
  to keep answering "who saw this".

SQLite with the Postgres type shims behind an async facade, like the sibling
announcement tests: the assertions are about rows, and only a real engine can
falsify them.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import MagicMock

import sqlalchemy as sa
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.platform.audit import AuditLog  # noqa: E402
from shared.models.platform.notification import Notification, NotificationRead  # noqa: E402
from shared.testing import install_postgres_type_shims  # noqa: E402
from src.rpc import notifications_admin as admin_rpc  # noqa: E402

install_postgres_type_shims()

# ``auth.user`` is here because the operator list LEFT-joins it for the
# recipient's name; the join being outer is what the "account is gone" pin below
# actually exercises.
TABLES = (Notification.__table__, NotificationRead.__table__, AuditLog.__table__, AuthUser.__table__)

WORKSPACE = 7
OTHER_WORKSPACE = 9
RECIPIENT = 500

PAST = datetime.now(UTC) - timedelta(hours=1)

# Owner of workspace 7 and nothing else: the owner role carries every
# non-governance action there, which is what makes the 403 on workspace 9 a
# statement about scope rather than about the grant.
OWNER = {
    "user_id": 2,
    "username": "owner",
    "is_active": True,
    "is_superuser": False,
    "workspaces": [{"workspace_id": WORKSPACE, "rbac_roles": ["owner"], "rbac_permissions": []}],
}

OUTSIDER = {"user_id": 3, "username": "outsider", "is_active": True, "is_superuser": False, "workspaces": []}


class _AsyncSessionShim:
    """Async facade over a synchronous ``Session``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def execute(self, statement: Any) -> Any:
        return self._session.execute(statement)

    async def scalar(self, statement: Any) -> Any:
        return self._session.scalar(statement)

    async def get(self, entity: Any, ident: Any) -> Any:
        return self._session.get(entity, ident)

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    async def flush(self) -> None:
        self._session.flush()

    async def refresh(self, instance: Any, attribute_names: Any = None) -> None:
        self._session.refresh(instance, attribute_names)

    async def commit(self) -> None:
        self._session.commit()


class _SessionMaker:
    def __init__(self, shim: _AsyncSessionShim) -> None:
        self._shim = shim

    def __call__(self) -> _SessionMaker:
        return self

    async def __aenter__(self) -> _AsyncSessionShim:
        return self._shim

    async def __aexit__(self, *exc: object) -> bool:
        return False


class NotificationAdminRpcTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = sa.create_engine(
            "sqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        with self.engine.begin() as conn:
            for schema in sorted({table.schema for table in TABLES if table.schema}):
                conn.exec_driver_sql(f"ATTACH DATABASE ':memory:' AS {schema}")
            for table in TABLES:
                table.create(conn)
        self.session = Session(self.engine, expire_on_commit=False)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.session.close)

        maker = _SessionMaker(_AsyncSessionShim(self.session))
        self.handlers: dict[str, Any] = {}
        broker = MagicMock()
        broker.subscriber = self._capture
        admin_rpc.register(broker, MagicMock())
        original = admin_rpc._SF
        admin_rpc._SF = maker
        self.addCleanup(setattr, admin_rpc, "_SF", original)

    def _capture(self, subject: str, *args: Any, **kwargs: Any):
        def decorator(fn):
            self.handlers[subject] = fn
            return fn

        return decorator

    # -- helpers -----------------------------------------------------------

    async def call(self, subject: str, data: dict[str, Any]) -> dict[str, Any]:
        return await self.handlers[subject](data, MagicMock())

    def produced(self, **values: Any) -> int:
        values.setdefault("kind", "registration.approved")
        values.setdefault("audience", "user")
        values.setdefault("recipient_auth_user_id", RECIPIENT)
        values.setdefault("source_workspace_id", WORKSPACE)
        values.setdefault("published_at", PAST)
        row = Notification(**values)
        self.session.add(row)
        self.session.flush()
        return row.id

    def recipient(self, auth_user_id: int = RECIPIENT, username: str = "recipient") -> int:
        self.session.add(AuthUser(id=auth_user_id, email=f"{username}@example.test", username=username))
        self.session.flush()
        return auth_user_id

    async def listed(self, identity: dict, **query: Any) -> dict[str, Any]:
        query.setdefault("workspace_id", WORKSPACE)
        return await self.call("rpc.app.notification_admin_list", {"identity": identity, "query": query})

    async def retire(self, identity: dict, **body: Any) -> dict[str, Any]:
        body.setdefault("workspace_id", WORKSPACE)
        return await self.call("rpc.app.notification_admin_retire", {"identity": identity, "payload": body})

    def expires_at(self, notification_id: int) -> datetime | None:
        self.session.expire_all()
        return self.session.get(Notification, notification_id).expires_at

    # -- scope -------------------------------------------------------------

    async def test_list_is_confined_to_the_workspace_that_produced_the_rows(self) -> None:
        mine = self.produced()
        self.produced(source_workspace_id=OTHER_WORKSPACE)
        # A row from before the source column existed: no tenant, so no operator
        # may claim it -- it must not fall into whoever asks first.
        self.produced(source_workspace_id=None)

        result = await self.listed(OWNER)

        self.assertTrue(result["ok"], result)
        self.assertEqual([item["id"] for item in result["data"]["results"]], [mine])

    async def test_the_list_names_the_recipient_and_survives_a_deleted_account(self) -> None:
        self.recipient(username="told")
        named = self.produced()
        orphaned = self.produced(recipient_auth_user_id=999)

        result = await self.listed(OWNER)

        self.assertTrue(result["ok"], result)
        rows = {item["id"]: item for item in result["data"]["results"]}
        self.assertEqual(rows[named]["recipient_username"], "told")
        self.assertIsNone(rows[orphaned]["recipient_username"])
        self.assertEqual(rows[orphaned]["recipient_auth_user_id"], 999)

    async def test_the_list_pages_by_number_and_counts_only_the_filtered_scope(self) -> None:
        oldest, middle, newest = [self.produced(published_at=PAST - timedelta(minutes=n)) for n in (3, 2, 1)]
        self.produced(kind="team_invite.received")
        self.produced(source_workspace_id=OTHER_WORKSPACE)

        first = await self.listed(OWNER, kind="registration.approved", per_page=2)
        second = await self.listed(OWNER, kind="registration.approved", per_page=2, page=2)

        self.assertTrue(first["ok"], first)
        self.assertEqual(first["data"]["total"], 3)
        self.assertEqual([item["id"] for item in first["data"]["results"]], [newest, middle])
        self.assertEqual([item["id"] for item in second["data"]["results"]], [oldest])

    async def test_a_foreign_workspace_is_refused_even_for_a_workspace_owner(self) -> None:
        self.produced(source_workspace_id=OTHER_WORKSPACE)

        refused = await self.listed(OWNER, workspace_id=OTHER_WORKSPACE)
        anonymous = await self.listed(OUTSIDER)

        self.assertFalse(refused["ok"], refused)
        self.assertFalse(anonymous["ok"], anonymous)

    async def test_announcements_are_not_reachable_through_this_screen(self) -> None:
        """They own a different CRUD; two delete buttons for one row is a bug."""
        system_row = self.produced()
        announcement = self.produced(
            kind="announcement.published",
            audience="workspace",
            recipient_auth_user_id=None,
            workspace_id=WORKSPACE,
        )

        result = await self.listed(OWNER)
        retired = await self.retire(OWNER, ids=[announcement])

        self.assertEqual([item["id"] for item in result["data"]["results"]], [system_row])
        self.assertEqual(retired["data"]["retired"], 0)
        self.assertIsNone(self.expires_at(announcement))

    # -- retire ------------------------------------------------------------

    async def test_retiring_a_kind_expires_exactly_that_kind_and_audits_it(self) -> None:
        approved = self.produced(kind="registration.approved")
        also_approved = self.produced(kind="registration.approved")
        invite = self.produced(kind="team_invite.received")
        neighbour = self.produced(kind="registration.approved", source_workspace_id=OTHER_WORKSPACE)

        result = await self.retire(OWNER, kind="registration.approved")

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["retired"], 2)
        self.assertIsNotNone(self.expires_at(approved))
        self.assertIsNotNone(self.expires_at(also_approved))
        self.assertIsNone(self.expires_at(invite))
        self.assertIsNone(self.expires_at(neighbour), "another tenant's rows are not this operator's to retire")

        audit = self.session.scalars(sa.select(AuditLog)).all()
        self.assertEqual([entry.action for entry in audit], ["notification.delete"])
        self.assertEqual(audit[0].workspace_id, WORKSPACE)
        self.assertEqual(audit[0].after_json["retired"], 2)

    async def test_retire_keeps_the_row_and_its_read_marks(self) -> None:
        """A retire is not a DELETE: the inbox still has to answer "who saw it"."""
        row = self.produced()
        self.session.add(NotificationRead(auth_user_id=RECIPIENT, notification_id=row))
        self.session.flush()

        await self.retire(OWNER, ids=[row])

        self.assertIsNotNone(self.session.get(Notification, row))
        self.assertEqual(
            [(mark.auth_user_id, mark.notification_id) for mark in self.session.scalars(sa.select(NotificationRead))],
            [(RECIPIENT, row)],
        )

    async def test_a_foreign_id_is_dropped_rather_than_rejected(self) -> None:
        """No existence oracle, the same rule the inbox's own writes follow."""
        mine = self.produced()
        neighbour = self.produced(source_workspace_id=OTHER_WORKSPACE)

        result = await self.retire(OWNER, ids=[neighbour, 10_000])

        self.assertTrue(result["ok"], result)
        self.assertEqual(result["data"]["retired"], 0)
        self.assertIsNone(self.expires_at(neighbour))

        # Control: the same call shape does retire an id this operator owns.
        ok = await self.retire(OWNER, ids=[mine, neighbour])
        self.assertEqual(ok["data"]["retired"], 1)
        self.assertIsNotNone(self.expires_at(mine))

    async def test_a_repeat_retire_neither_errors_nor_moves_the_expiry(self) -> None:
        row = self.produced()
        await self.retire(OWNER, ids=[row])
        first = self.expires_at(row)

        again = await self.retire(OWNER, ids=[row])

        self.assertTrue(again["ok"], again)
        self.assertEqual(again["data"]["retired"], 0)
        self.assertEqual(self.expires_at(row), first)

    async def test_retiring_nothing_in_particular_is_refused(self) -> None:
        """ "Everything this tenant ever sent" must be spelled out, not omitted."""
        row = self.produced()

        result = await self.retire(OWNER)

        self.assertFalse(result["ok"], result)
        self.assertIsNone(self.expires_at(row))

    async def test_an_unknown_kind_is_refused_on_both_verbs(self) -> None:
        row = self.produced()

        listed = await self.listed(OWNER, kind="nope.nope")
        retired = await self.retire(OWNER, kind="nope.nope")

        self.assertFalse(listed["ok"], listed)
        self.assertFalse(retired["ok"], retired)
        self.assertIsNone(self.expires_at(row))
