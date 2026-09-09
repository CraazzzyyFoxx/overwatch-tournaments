"""The registration admin handlers must append to the platform audit log.

Registrations are driven by bespoke lifecycle services rather than the shared
CRUD dispatcher, and nothing here called ``record_audit`` -- so every edit an
admin made left the feed and the per-entity trail empty. These tests pin the
three properties that made the gap invisible:

* an edit stages exactly one ``registration.update`` row, with a before/after
  image of the fields that really changed;
* a save that changes nothing stages no row, so the journal stays a record of
  changes rather than a transcript of the form;
* the row is staged BEFORE the service that owns the ``commit()`` runs, which is
  what keeps a rejected edit from leaving a trail of having happened.
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

registration_admin = importlib.import_module("src.rpc.registration_admin")
helpers = importlib.import_module("src.rpc._helpers")

WORKSPACE_ID = 1
REGISTRATION_ID = 55

#: Grants the "team create"/"team update" gates the handlers check on workspace 1.
IDENTITY = make_identity(
    username="organizer",
    workspaces=[
        {
            "workspace_id": WORKSPACE_ID,
            "rbac_roles": [],
            "rbac_permissions": [
                {"resource": "team", "action": "create"},
                {"resource": "team", "action": "update"},
            ],
        }
    ],
)


class _FakeSession:
    """Records the ordered trace of audit writes and commits.

    ``add`` is the only write ``record_audit`` performs, so the rows it collects
    are exactly the journal this suite is about; ``trace`` also carries the
    service call, which is how the staging-order test tells the two apart.
    """

    def __init__(self, trace: list[str]) -> None:
        self.rows: list[Any] = []
        self.trace = trace

    def add(self, row: Any) -> None:
        self.rows.append(row)
        self.trace.append("audit")

    async def commit(self) -> None:
        self.trace.append("commit")

    async def flush(self) -> None:  # pragma: no cover - not reached by these paths
        pass


def _role(role: str, rank_value: int | None) -> SimpleNamespace:
    return SimpleNamespace(
        role=role,
        subrole=None,
        rank_value=rank_value,
        is_primary=True,
        is_active=True,
        hero_entries=[],
    )


def _registration(**overrides: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": REGISTRATION_ID,
        "tournament_id": 3,
        "display_name": "Ferz",
        "battle_tag": "Ferz#2100",
        "smurf_tags_json": None,
        "discord_nick": "ferz",
        "twitch_nick": None,
        "boosty_nick": None,
        "stream_pov": False,
        "notes": None,
        "admin_notes": None,
        "custom_fields_json": None,
        "status": "pending",
        "balancer_status": "not_in_balancer",
        "exclude_reason": None,
        "checked_in": False,
        "roles": [_role("dps", 30)],
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _update_payload(**overrides: Any) -> dict[str, Any]:
    """The whole form, the way the admin editor submits it on every save."""
    payload: dict[str, Any] = {
        "display_name": "Ferz",
        "battle_tag": "Ferz#2100",
        "discord_nick": "ferz",
        "stream_pov": False,
        "status": "pending",
        "balancer_status": "not_in_balancer",
        "roles": [
            {
                "role": "dps",
                "subrole": None,
                "priority": 0,
                "is_primary": True,
                "rank_value": 30,
                "is_active": True,
                "top_heroes": None,
            }
        ],
    }
    payload.update(overrides)
    return payload


class RegistrationAuditTests(IsolatedAsyncioTestCase):
    async def _invoke(
        self,
        subject: str,
        data: dict[str, Any],
        *,
        stored: SimpleNamespace,
        service_attr: str,
    ) -> tuple[dict[str, Any], _FakeSession, list[str]]:
        broker = CapturingBroker()
        registration_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        trace: list[str] = []
        session = _FakeSession(trace)

        async def fake_ws_id(_session, _registration_id):
            return WORKSPACE_ID

        async def fake_get(_session, _registration_id):
            return stored

        async def fake_service(*_args, **_kwargs):
            trace.append("service")
            return stored

        async def fake_status_metas(_session, *, workspace_id):
            return {}

        async def fake_emit(*_args, **_kwargs):
            return None

        async def fake_rosters(*_args, **_kwargs):
            return {}

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(registration_admin.auth, "get_registration_workspace_id", fake_ws_id),
            patch.object(registration_admin.lifecycle.lifecycle_service, "get_registration_by_id", fake_get),
            patch.object(registration_admin.lifecycle.lifecycle_service, service_attr, fake_service),
            patch.object(registration_admin, "get_status_metas_map", fake_status_metas),
            patch.object(registration_admin, "emit_balancer_registrations_changed", fake_emit),
            patch.object(registration_admin, "serialize_registration", lambda *a, **k: {}),
            patch.object(registration_admin.roster_engine, "resolve", fake_rosters),
        ):
            envelope = await broker.handlers[subject](data, None)
        return envelope, session, trace

    async def test_edit_records_one_row_with_the_fields_that_changed(self):
        envelope, session, _ = await self._invoke(
            "rpc.tournament.reg_update",
            {
                "identity": IDENTITY,
                "id": REGISTRATION_ID,
                "payload": _update_payload(
                    admin_notes="smurf suspected",
                    roles=[
                        {
                            "role": "dps",
                            "subrole": None,
                            "priority": 0,
                            "is_primary": True,
                            "rank_value": 42,
                            "is_active": True,
                            "top_heroes": None,
                        }
                    ],
                ),
            },
            stored=_registration(),
            service_attr="update_registration_profile",
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(1, len(session.rows))
        row = session.rows[0]
        self.assertEqual("registration.update", row.action)
        self.assertEqual("registration", row.entity_type)
        self.assertEqual(REGISTRATION_ID, row.entity_id)
        self.assertEqual(WORKSPACE_ID, row.workspace_id)
        self.assertEqual(7, row.actor_auth_user_id)
        self.assertEqual("organizer", row.actor_label)
        # The name is snapshotted, not joined: nothing points at the row later.
        self.assertEqual("Ferz", row.entity_label)

        # Only what moved: the untouched half of the form must not appear.
        self.assertEqual({"admin_notes", "roles"}, set(row.after_json))
        self.assertIsNone(row.before_json["admin_notes"])
        self.assertEqual("smurf suspected", row.after_json["admin_notes"])
        self.assertEqual(30, row.before_json["roles"][0]["rank_value"])
        self.assertEqual(42, row.after_json["roles"][0]["rank_value"])

    async def test_edit_that_changes_nothing_records_nothing(self):
        envelope, session, _ = await self._invoke(
            "rpc.tournament.reg_update",
            {"identity": IDENTITY, "id": REGISTRATION_ID, "payload": _update_payload()},
            stored=_registration(),
            service_attr="update_registration_profile",
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([], session.rows)

    async def test_battle_tag_resave_in_other_casing_is_not_a_change(self):
        """``normalize_battle_tag`` collapses spacing around '#'; without applying
        it to the requested value first, a resave reads as an edit."""
        envelope, session, _ = await self._invoke(
            "rpc.tournament.reg_update",
            {
                "identity": IDENTITY,
                "id": REGISTRATION_ID,
                "payload": _update_payload(battle_tag="Ferz #2100"),
            },
            stored=_registration(),
            service_attr="update_registration_profile",
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([], session.rows)

    async def test_row_is_staged_before_the_service_commits(self):
        _, _, trace = await self._invoke(
            "rpc.tournament.reg_update",
            {
                "identity": IDENTITY,
                "id": REGISTRATION_ID,
                "payload": _update_payload(admin_notes="checked"),
            },
            stored=_registration(),
            service_attr="update_registration_profile",
        )

        # Staged first, so the row rides the transaction the service commits:
        # reversed, a rejected edit would keep its audit trail. The trailing
        # commit is the realtime rail's: the handler stages the admin-tool
        # signal after the service has already committed, so releasing it needs
        # a commit of its own.
        self.assertEqual(["audit", "service", "commit"], trace)

    async def test_approve_records_the_status_transition(self):
        _, session, _ = await self._invoke(
            "rpc.tournament.reg_approve",
            {"identity": IDENTITY, "id": REGISTRATION_ID},
            stored=_registration(),
            service_attr="approve_registration",
        )

        self.assertEqual(1, len(session.rows))
        row = session.rows[0]
        self.assertEqual("registration.approve", row.action)
        self.assertEqual({"status": "pending"}, row.before_json)
        self.assertEqual({"status": "approved"}, row.after_json)

    async def test_check_in_undo_is_a_distinct_action(self):
        _, session, _ = await self._invoke(
            "rpc.tournament.reg_check_in",
            {"identity": IDENTITY, "id": REGISTRATION_ID, "payload": {"checked_in": False}},
            stored=_registration(checked_in=True),
            service_attr="uncheck_in_registration",
        )

        self.assertEqual(1, len(session.rows))
        row = session.rows[0]
        self.assertEqual("registration.check_in_undo", row.action)
        self.assertEqual({"checked_in": True}, row.before_json)
        self.assertEqual({"checked_in": False}, row.after_json)

    async def test_bulk_approve_is_filed_on_the_tournament(self):
        broker = CapturingBroker()
        registration_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        trace: list[str] = []
        session = _FakeSession(trace)

        async def fake_ws_id(_session, _tournament_id):
            return WORKSPACE_ID

        async def fake_bulk(*_args, **_kwargs):
            trace.append("service")
            return 2, 1

        async def fake_emit(*_args, **_kwargs):
            return None

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(registration_admin.auth, "get_tournament_workspace_id", fake_ws_id),
            patch.object(registration_admin.lifecycle.lifecycle_service, "bulk_approve_registrations", fake_bulk),
            patch.object(registration_admin, "emit_balancer_registrations_changed", fake_emit),
        ):
            envelope = await broker.handlers["rpc.tournament.reg_bulk_approve"](
                {"identity": IDENTITY, "id": 3, "payload": {"registration_ids": [1, 2, 9]}},
                None,
            )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(1, len(session.rows), "a bulk request must not fan out one row per registration")
        row = session.rows[0]
        self.assertEqual("registration.bulk_approve", row.action)
        self.assertEqual("tournament", row.entity_type)
        self.assertEqual(3, row.entity_id)
        self.assertEqual([1, 2, 9], row.after_json["registration_ids"])
        # Trailing commit: see test_row_is_staged_before_the_service_commits.
        self.assertEqual(["audit", "service", "commit"], trace)
