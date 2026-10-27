"""A status that admits or refuses a player takes the same grant on every path.

``reg_approve`` / ``reg_reject`` need ``registration.approve`` / ``.reject``, but the
profile editor (``reg_update``) and the manual create (``reg_create_manual``) used to
write the very same statuses with only ``registration.update`` / ``.create``. Now a
status CHANGE to ``approved`` needs ``approve`` and one to ``rejected`` / ``banned``
needs ``reject``; a resent unchanged status (the editor round-trips its whole form)
and a manual row's default ``approved`` need nothing extra.

Also here: ``reg_user_rank_history`` answers a caller without ``registration.read``
with 403 before it validates the discipline, so its 422s say nothing to outsiders.
"""

from __future__ import annotations

import importlib
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

registration_admin = importlib.import_module("src.rpc.registration_admin")
helpers = importlib.import_module("src.rpc._helpers")

from shared.models.registration.registration import Registration  # noqa: E402

WORKSPACE_ID = 1
TOURNAMENT_ID = 3
REGISTRATION_ID = 55


def _identity(*actions: str) -> dict[str, Any]:
    return make_identity(
        username="staff",
        workspaces=[
            {
                "workspace_id": WORKSPACE_ID,
                "rbac_roles": [],
                "rbac_permissions": [{"resource": "registration", "action": action} for action in actions],
            }
        ],
    )


def _registration(status: str) -> SimpleNamespace:
    registration = SimpleNamespace(
        id=REGISTRATION_ID,
        tournament_id=TOURNAMENT_ID,
        tournament=SimpleNamespace(discipline="overwatch"),
        display_name="Ferz",
        identities=[],
        roles=[],
        status=status,
        balancer_status="not_in_balancer",
    )
    registration.primary_game_identity = partial(Registration.primary_game_identity, registration)
    return registration


class StatusWritePermissionTests(IsolatedAsyncioTestCase):
    async def _call(
        self, subject: str, identity: dict[str, Any], payload: dict[str, Any], *, stored_status: str = "pending"
    ) -> tuple[dict[str, Any], list[Any], list[Any]]:
        """Run one handler; returns the envelope, the statuses the service was asked to write, and the audit rows."""
        broker = CapturingBroker()
        registration_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        stored = _registration(stored_status)
        written: list[Any] = []
        rows: list[Any] = []
        session = SimpleNamespace(add=rows.append, commit=AsyncMock())

        async def workspace_of(_session: Any, _id: int) -> int:
            return WORKSPACE_ID

        async def get(_session: Any, _registration_id: int) -> SimpleNamespace:
            return stored

        async def write(_session: Any, *_args: Any, **kwargs: Any) -> SimpleNamespace:
            written.append(kwargs["status_value"])
            return stored

        async def nothing(*_args: Any, **_kwargs: Any) -> None:
            return None

        async def restore(_session: Any, _registration_id: int, **_kwargs: Any) -> SimpleNamespace:
            # ``restore_registration`` always lands ``approved``.
            written.append("approved")
            return stored

        async def no_rosters(*_args: Any, **_kwargs: Any) -> dict:
            return {}

        async def no_metas(_session: Any, *, workspace_id: int) -> dict:
            return {}

        service = registration_admin.lifecycle.lifecycle_service
        record_id = TOURNAMENT_ID if subject == "rpc.tournament.reg_create_manual" else REGISTRATION_ID
        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)),
            patch.object(registration_admin.auth, "get_registration_workspace_id", workspace_of),
            patch.object(registration_admin.auth, "get_tournament_workspace_id", workspace_of),
            patch.object(registration_admin.reg_common._common_service, "ensure_tournament_exists", nothing),
            patch.object(service, "get_registration_by_id", get),
            patch.object(service, "update_registration_profile", write),
            patch.object(service, "create_manual_registration", write),
            patch.object(service, "restore_registration", restore),
            patch.object(registration_admin, "get_status_metas_map", no_metas),
            patch.object(registration_admin, "emit_balancer_registrations_changed", nothing),
            patch.object(registration_admin, "serialize_registration", lambda *a, **k: {}),
            patch.object(registration_admin.roster_engine, "resolve", no_rosters),
        ):
            envelope = await broker.handlers[subject]({"identity": identity, "id": record_id, "payload": payload}, None)
        return envelope, written, rows

    def assertRefused(self, envelope: dict[str, Any], written: list[Any], rows: list[Any], action: str) -> None:
        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("forbidden", envelope["error"]["code"])
        self.assertIn(f"registration.{action}", envelope["error"]["message"])
        # Refused before any write: no service call, no audit row staged.
        self.assertEqual([], written)
        self.assertEqual([], rows)

    async def test_an_edit_cannot_approve_or_refuse_on_update_alone(self) -> None:
        for status, action in (("approved", "approve"), ("rejected", "reject"), ("banned", "reject")):
            with self.subTest(status=status):
                self.assertRefused(
                    *await self._call("rpc.tournament.reg_update", _identity("update"), {"status": status}),
                    action,
                )

    async def test_an_edit_with_the_matching_grant_writes_the_status(self) -> None:
        for status, action in (("approved", "approve"), ("rejected", "reject"), ("banned", "reject")):
            with self.subTest(status=status):
                envelope, written, _ = await self._call(
                    "rpc.tournament.reg_update", _identity("update", action), {"status": status}
                )
                self.assertTrue(envelope["ok"], envelope)
                self.assertEqual([status], written)

    async def test_a_resent_unchanged_status_needs_no_extra_grant(self) -> None:
        envelope, written, _ = await self._call(
            "rpc.tournament.reg_update", _identity("update"), {"status": "approved"}, stored_status="approved"
        )
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(["approved"], written)

    async def test_other_statuses_stay_with_update(self) -> None:
        for status in ("pending", "withdrawn", "insufficient_data"):
            with self.subTest(status=status):
                envelope, written, _ = await self._call(
                    "rpc.tournament.reg_update", _identity("update"), {"status": status}, stored_status="approved"
                )
                self.assertTrue(envelope["ok"], envelope)
                self.assertEqual([status], written)

    async def test_a_manual_create_cannot_refuse_on_create_alone(self) -> None:
        for status in ("rejected", "banned"):
            with self.subTest(status=status):
                self.assertRefused(
                    *await self._call("rpc.tournament.reg_create_manual", _identity("create"), {"status": status}),
                    "reject",
                )

    async def test_a_manual_create_with_reject_writes_the_refusal(self) -> None:
        envelope, written, _ = await self._call(
            "rpc.tournament.reg_create_manual", _identity("create", "reject"), {"status": "rejected"}
        )
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(["rejected"], written)

    async def test_a_manual_create_lands_on_its_default_approved_with_create_alone(self) -> None:
        for payload in ({}, {"status": "approved"}):
            with self.subTest(payload=payload):
                envelope, written, _ = await self._call(
                    "rpc.tournament.reg_create_manual", _identity("create"), payload
                )
                self.assertTrue(envelope["ok"], envelope)
                self.assertEqual([payload.get("status")], written)

    async def test_a_restore_cannot_approve_on_update_alone(self) -> None:
        """A restore lands ``approved``: the same grant ``reg_approve`` needs."""
        self.assertRefused(
            *await self._call("rpc.tournament.reg_restore", _identity("update"), {}, stored_status="withdrawn"),
            "approve",
        )

    async def test_a_restore_with_approve_lands_approved(self) -> None:
        envelope, written, _ = await self._call(
            "rpc.tournament.reg_restore", _identity("update", "approve"), {}, stored_status="withdrawn"
        )
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(["approved"], written)


class RankHistoryPermissionOrderTests(IsolatedAsyncioTestCase):
    async def test_an_outsider_is_refused_before_the_query_is_validated(self) -> None:
        broker = CapturingBroker()
        registration_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        with patch.object(helpers.db, "async_session_maker", FakeSessionMaker()):
            for query in ({"workspace_id": ["1"]}, {"workspace_id": ["1"], "discipline": ["no-such-game"]}):
                with self.subTest(query=query):
                    envelope = await broker.handlers["rpc.tournament.reg_user_rank_history"](
                        {"identity": _identity("update"), "user_id": 9, "query": query}, None
                    )
                    self.assertFalse(envelope["ok"], envelope)
                    self.assertEqual("forbidden", envelope["error"]["code"])
