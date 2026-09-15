"""``rpc.tournament.regstatus_create``/``regstatus_update`` must forward every
custom-status field from the validated request body to ``status_catalog``.

Regression test: the handlers used to validate
``BalancerRegistrationStatusCreate``/``Update`` (which carry
``excludes_from_balancer``/``excludes_from_ready``) but never actually passed
either field to ``status_catalog.create_custom_status``/``update_custom_status``
-- so toggling "Excludes from balancer pool" or "Blocks Ready" in the admin UI
silently did nothing. Nothing else in the suite calls these handlers, so the
gap was invisible.
"""

from __future__ import annotations

import importlib
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

registration_admin = importlib.import_module("src.rpc.registration_admin")
helpers = importlib.import_module("src.rpc._helpers")

CREATED_AT = datetime(2026, 5, 1, 12, 30, tzinfo=UTC)

#: Grants the "registration_status" create/update gates the two subjects check
#: on workspace 1 (moved off the legacy blanket "team" resource).
IDENTITY = make_identity(
    workspaces=[
        {
            "workspace_id": 1,
            "rbac_roles": [],
            "rbac_permissions": [
                {"resource": "registration_status", "action": "create"},
                {"resource": "registration_status", "action": "update"},
            ],
        }
    ],
)


def _status_row(**overrides) -> SimpleNamespace:
    base = {
        "id": 42,
        "workspace_id": 1,
        "scope": "balancer",
        "slug": "injured",
        "kind": "custom",
        "icon_slug": None,
        "icon_color": None,
        "name": "Injured",
        "description": None,
        "excludes_from_balancer": False,
        "excludes_from_ready": False,
        "created_at": CREATED_AT,
        "updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class RegstatusHandlersForwardExclusionFlags(IsolatedAsyncioTestCase):
    async def _invoke(self, subject: str, data: dict, *, service_fn, service_result):
        broker = CapturingBroker()
        registration_admin.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        self.assertIn(subject, broker.handlers, "subject is not registered")

        calls: list[dict] = []

        async def stub(session, **kwargs):
            calls.append(kwargs)
            return service_result

        with (
            patch.object(helpers.db, "async_session_maker", FakeSessionMaker()),
            patch.object(registration_admin.status_catalog.status_catalog_service, service_fn, stub),
        ):
            envelope = await broker.handlers[subject](data, None)
        return envelope, calls

    async def test_create_forwards_excludes_from_balancer_and_excludes_from_ready(self):
        envelope, calls = await self._invoke(
            "rpc.tournament.regstatus_create",
            {
                "identity": IDENTITY,
                "workspace_id": 1,
                "payload": {
                    "scope": "balancer",
                    "name": "Injured",
                    "excludes_from_balancer": True,
                    "excludes_from_ready": True,
                },
            },
            service_fn="create_custom_status",
            service_result=_status_row(excludes_from_balancer=True, excludes_from_ready=True),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0]["excludes_from_balancer"])
        self.assertTrue(calls[0]["excludes_from_ready"])

    async def test_create_defaults_both_flags_to_false(self):
        envelope, calls = await self._invoke(
            "rpc.tournament.regstatus_create",
            {
                "identity": IDENTITY,
                "workspace_id": 1,
                "payload": {"scope": "balancer", "name": "Standby"},
            },
            service_fn="create_custom_status",
            service_result=_status_row(slug="standby", name="Standby"),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(1, len(calls))
        self.assertFalse(calls[0]["excludes_from_balancer"])
        self.assertFalse(calls[0]["excludes_from_ready"])

    async def test_update_forwards_excludes_from_balancer_and_excludes_from_ready(self):
        envelope, calls = await self._invoke(
            "rpc.tournament.regstatus_update",
            {
                "identity": IDENTITY,
                "workspace_id": 1,
                "status_id": 42,
                "payload": {
                    "excludes_from_balancer": True,
                    "excludes_from_ready": True,
                },
            },
            service_fn="update_custom_status",
            service_result=_status_row(excludes_from_balancer=True, excludes_from_ready=True),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(1, len(calls))
        self.assertTrue(calls[0]["excludes_from_balancer"])
        self.assertTrue(calls[0]["excludes_from_ready"])

    async def test_update_omitting_flags_leaves_them_unset(self):
        """A PATCH that only renames the status must not clobber either flag --
        ``status_catalog.update_custom_status`` treats ``None`` as "leave it"."""
        envelope, calls = await self._invoke(
            "rpc.tournament.regstatus_update",
            {
                "identity": IDENTITY,
                "workspace_id": 1,
                "status_id": 42,
                "payload": {"name": "Renamed"},
            },
            service_fn="update_custom_status",
            service_result=_status_row(name="Renamed"),
        )

        self.assertTrue(envelope.get("ok"), envelope)
        self.assertEqual(1, len(calls))
        self.assertIsNone(calls[0]["excludes_from_balancer"])
        self.assertIsNone(calls[0]["excludes_from_ready"])
