"""The integration handlers must append to the platform audit log.

Challonge syncs, Google Sheet feeds and division-grid edits all ran through
services that own their own ``commit()``, so nothing in ``rpc/integrations``
left a journal entry. These tests pin the three properties that keep the added
rows honest:

* an operator Challonge sync is filed under ``source="challonge"`` and staged
  BEFORE the service that commits -- staging it after would put the row in a
  second transaction that never runs;
* a Sheets write stays a plain ``admin`` row scoped to the tournament, carrying
  named feed fields rather than the request body;
* a division-grid write is staged before the handler's own ``commit()``, in the
  workspace the permission check used (resolved from the row, never from the
  client).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

integrations = importlib.import_module("src.rpc.integrations")
helpers = importlib.import_module("src.rpc._helpers")

WORKSPACE_ID = 4
TOURNAMENT_ID = 12
VERSION_ID = 77
GRID_ID = 9

IDENTITY = make_identity(
    username="organizer",
    workspaces=[
        {
            "workspace_id": WORKSPACE_ID,
            "rbac_roles": [],
            "rbac_permissions": [
                {"resource": "challonge", "action": "update"},
                {"resource": "team", "action": "create"},
                {"resource": "division_grid", "action": "update"},
            ],
        }
    ],
)


class _FakeSession:
    """Records the ordered trace of audit writes and commits."""

    def __init__(self, trace: list[str]) -> None:
        self.rows: list[Any] = []
        self.trace = trace

    def add(self, row: Any) -> None:
        self.rows.append(row)
        self.trace.append("audit")

    async def commit(self) -> None:
        self.trace.append("commit")


def _quota_gate(trace: list[str]) -> SimpleNamespace:
    """The quota gate as a pass-through that records its slug and its turn."""

    async def charge(_user: Any, operation: str, **_kwargs: Any) -> None:
        trace.append(f"quota:{operation}")

    return SimpleNamespace(charge=charge)


class IntegrationsAuditTests(IsolatedAsyncioTestCase):
    def _handler(self, subject: str):
        broker = CapturingBroker()
        integrations.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")
        return broker.handlers[subject]

    async def test_challonge_import_is_a_challonge_row_staged_before_the_sync(self):
        handler = self._handler("rpc.tournament.challonge_import")
        trace: list[str] = []
        session = _FakeSession(trace)

        async def fake_permission(*_args, **_kwargs):
            return None

        async def fake_ws_id(_session, _tournament_id):
            return WORKSPACE_ID

        async def fake_import(_session, _tournament_id, *, dry_run):
            trace.append("service")
            return {"encounters": 0}

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(integrations.auth, "require_tournament_id_permission", fake_permission),
            patch.object(integrations.auth, "get_tournament_workspace_id", fake_ws_id),
            patch.object(integrations.challonge_sync.sync_service, "import_tournament", fake_import),
            patch.object(integrations, "quota", _quota_gate(trace)),
        ):
            envelope = await handler({"identity": IDENTITY, "id": TOURNAMENT_ID}, None)

        self.assertTrue(envelope["ok"], envelope)
        # The third-party spend is metered before Challonge is touched at all.
        self.assertEqual(["quota:tournament.challonge_import", "audit", "service"], trace)
        (row,) = session.rows
        self.assertEqual("challonge.import", row.action)
        self.assertEqual("challonge", row.source)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)
        self.assertEqual(("tournament", TOURNAMENT_ID), (row.entity_type, row.entity_id))
        self.assertEqual({"dry_run": False}, row.after_json)

    async def test_sheet_upsert_is_an_admin_row_with_named_feed_fields(self):
        handler = self._handler("rpc.tournament.sheet_upsert")
        trace: list[str] = []
        session = _FakeSession(trace)

        async def fake_permission(*_args, **_kwargs):
            return None

        async def fake_ws_id(_session, _tournament_id):
            return WORKSPACE_ID

        async def fake_upsert(_session, _tournament_id, **_kwargs):
            trace.append("service")
            return SimpleNamespace()

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(integrations.auth, "require_tournament_id_permission", fake_permission),
            patch.object(integrations.auth, "get_tournament_workspace_id", fake_ws_id),
            patch.object(integrations.sheet_sync.sheet_sync_service, "upsert_google_sheet_feed", fake_upsert),
            patch.object(integrations, "serialize_feed", lambda _feed: {}),
        ):
            envelope = await handler(
                {
                    "identity": IDENTITY,
                    "id": TOURNAMENT_ID,
                    "payload": {
                        "source_url": "https://docs.google.com/spreadsheets/d/abc/edit",
                        "title": "signups",
                        "auto_sync_enabled": True,
                    },
                },
                None,
            )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(["audit", "service"], trace)
        (row,) = session.rows
        self.assertEqual("registration.sheet_upsert", row.action)
        self.assertEqual("admin", row.source)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)
        self.assertEqual(("tournament", TOURNAMENT_ID), (row.entity_type, row.entity_id))
        self.assertEqual(
            {
                "source_url": "https://docs.google.com/spreadsheets/d/abc/edit",
                "title": "signups",
                "auto_sync_enabled": True,
                "auto_sync_interval_seconds": 300,
            },
            row.after_json,
        )

    async def test_version_publish_is_staged_before_the_route_commit(self):
        handler = self._handler("rpc.tournament.grid_version_publish")
        trace: list[str] = []
        session = _FakeSession(trace)
        version = SimpleNamespace(
            id=VERSION_ID,
            grid_id=GRID_ID,
            version=5,
            created_from_version_id=None,
            label="season 5",
            status="draft",
            published_at=None,
            grid=SimpleNamespace(id=GRID_ID, workspace_id=WORKSPACE_ID),
        )
        published = SimpleNamespace(
            id=VERSION_ID,
            grid_id=GRID_ID,
            version=5,
            created_from_version_id=None,
            label="season 5",
            status="published",
            published_at=None,
            grid=version.grid,
        )

        async def fake_workspace(_session, _workspace_id):
            return SimpleNamespace(id=WORKSPACE_ID)

        async def fake_get_version(_session, _version_id):
            return version

        async def fake_publish(_session, _version_id):
            trace.append("service")
            return published

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(integrations, "_get_workspace_or_404", fake_workspace),
            patch.object(integrations.division_grid_service, "get_version", fake_get_version),
            patch.object(integrations.division_grid_service, "publish_version", fake_publish),
            patch.object(integrations, "_dump", lambda obj, **_kwargs: {}),
        ):
            envelope = await handler({"identity": IDENTITY, "id": VERSION_ID}, None)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(["service", "audit", "commit"], trace)
        (row,) = session.rows
        self.assertEqual("division_grid.version_publish", row.action)
        self.assertEqual("admin", row.source)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)
        self.assertEqual(("division_grid", VERSION_ID), (row.entity_type, row.entity_id))
        self.assertEqual({"status": "published", "published_at": None}, row.after_json)
