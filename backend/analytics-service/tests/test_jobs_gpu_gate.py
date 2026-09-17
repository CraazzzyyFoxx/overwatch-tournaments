"""GPU gate: workspace-scoped analytics jobs need a verified/trusted workspace.

Self-service workspaces start ``unverified`` (see
``docs/superpowers/specs/2026-08-26-workspace-self-service-design.md`` §4.3), and
GPU compute is the expensive resource they must not reach. This drives the real
``src.rpc.jobs_control.register`` subscribers through a fake broker and asserts:

- ``kind=compute`` in an unverified workspace → 403 ``workspace_not_verified``
  *and* no ``AnalyticsJob`` row created (the gate runs before the insert);
- ``verified`` / ``trusted`` → unchanged pass-through;
- ``train_ml`` is untouched by this gate (still superuser-only);
- the deprecated ``train``/``infer`` publishers gate too (defense in depth).

The workspace read and the job insert are the only DB touches on this path, so
stubbing the repository + ``create_analytics_job`` keeps this a pure unit test
(same no-DB approach as ``test_analytics_route_permissions_app.py``).
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import AsyncMock, patch

# Ensure the analytics-service ``src`` package resolves regardless of pytest
# collection order / invocation cwd (matches how the suite is run).
_SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


from shared.models.tenancy.workspace import Workspace
from src.core import config, db
from src.rpc import jobs_control

# workspace_id → verification_status
_WORKSPACES = {1: "unverified", 2: "verified", 3: "trusted"}


class _FakeBroker:
    """Capture FastStream subscribers by subject, and swallow publishes."""

    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.published: list = []

    def subscriber(self, subject: str):
        def _decorator(fn):
            self.handlers[subject] = fn
            return fn

        return _decorator

    async def publish(self, *args, **kwargs):
        self.published.append(args[0] if args else kwargs.get("message"))
        return None


class _NoopSession:
    """Async session context; every query on this path is stubbed out."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeWorkspaces:
    """Stand-in for ``shared.repository.WorkspaceRepository``."""

    async def get(self, session, workspace_id, **kwargs):
        status = _WORKSPACES.get(int(workspace_id))
        if status is None:
            return None
        return Workspace(id=int(workspace_id), name=f"ws{workspace_id}", verification_status=status)


def _identity(*, workspace_ids=(), superuser=False, global_update=False) -> dict:
    update = [{"resource": "analytics", "action": "update"}]
    return {
        "user_id": 7,
        "is_active": True,
        "is_superuser": superuser,
        "roles": [],
        "permissions": update if global_update else [],
        "workspaces": [{"workspace_id": wid, "rbac_roles": [], "rbac_permissions": update} for wid in workspace_ids],
    }


class AnalyticsGpuGateTests(TestCase):
    def setUp(self) -> None:
        self._original_sf = db.async_session_maker
        db.async_session_maker = lambda: _NoopSession()
        self.broker = _FakeBroker()
        self.created: list[dict] = []

        async def _fake_create(session, **kwargs):
            self.created.append(kwargs)
            return SimpleNamespace(
                id=99,
                workspace_id=kwargs["workspace_id"],
                tournament_id=kwargs["tournament_id"],
                requested_by_user_id=kwargs["requested_by_user_id"],
                kind=kwargs["kind"],
                status="pending",
                algorithms=kwargs["algorithms"],
                training_workspace_ids=kwargs.get("training_workspace_ids"),
                progress={},
                error=None,
                started_at=None,
                finished_at=None,
                created_at=datetime(2026, 1, 1),
                updated_at=None,
            )

        self._patches = [
            patch.object(jobs_control, "_workspaces", _FakeWorkspaces()),
            patch.object(jobs_control, "create_analytics_job", _fake_create),
            patch.object(config.settings, "rabbitmq_url", "amqp://test"),
            # The gate is a process-global configured at service startup, which
            # these tests never run; the slug/workspace pairing it is handed is
            # covered where quota itself is tested.
            patch.object(jobs_control, "quota", SimpleNamespace(charge=AsyncMock())),
        ]
        for p in self._patches:
            p.start()
        jobs_control.register(self.broker, logging.getLogger("test"))

    def tearDown(self) -> None:
        for p in reversed(self._patches):
            p.stop()
        db.async_session_maker = self._original_sf

    def _call(self, subject: str, data: dict) -> dict:
        return asyncio.run(self.broker.handlers[subject](data, msg=None))

    def _create_job(self, workspace_id: int, **body) -> dict:
        return self._call(
            "rpc.analytics.create_job",
            {
                "identity": _identity(workspace_ids=(workspace_id,), **body.pop("identity_kwargs", {})),
                "query": {"workspace_id": str(workspace_id)},
                "payload": {"tournament_id": 5, **body},
            },
        )

    def test_compute_in_unverified_workspace_is_rejected_without_creating_a_job(self) -> None:
        envelope = self._create_job(1)

        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["code"], "forbidden")
        self.assertEqual(envelope["error"]["message"], "workspace_not_verified")
        self.assertEqual(self.created, [])

    def test_compute_in_verified_or_trusted_workspace_passes_through(self) -> None:
        for workspace_id in (2, 3):
            with self.subTest(status=_WORKSPACES[workspace_id]):
                self.created.clear()
                envelope = self._create_job(workspace_id)

                self.assertTrue(envelope["ok"], envelope)
                self.assertEqual(envelope["data"]["id"], 99)
                self.assertEqual([c["workspace_id"] for c in self.created], [workspace_id])

    def test_recalculate_and_points_share_the_gate(self) -> None:
        for subject, query in (
            ("rpc.analytics.recalculate", {"workspace_id": "1"}),
            ("rpc.analytics.points", {"workspace_id": "1", "tournament_id": "5"}),
        ):
            with self.subTest(subject=subject):
                envelope = self._call(
                    subject,
                    {
                        "identity": _identity(workspace_ids=(1,)),
                        "query": query,
                        "payload": {"tournament_id": 5},
                    },
                )

                self.assertFalse(envelope["ok"])
                self.assertEqual(envelope["error"]["message"], "workspace_not_verified")
                self.assertEqual(self.created, [])

    def test_train_ml_is_not_affected_by_the_verification_gate(self) -> None:
        # Non-superuser: still the pre-existing superuser 403, not the new one.
        envelope = self._create_job(1, kind="train_ml")
        self.assertFalse(envelope["ok"])
        self.assertEqual(envelope["error"]["message"], "Training ML models is restricted to superusers.")

        # Superuser: unverified workspace does not block training.
        envelope = self._create_job(1, kind="train_ml", identity_kwargs={"superuser": True})
        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([c["kind"] for c in self.created], ["train_ml"])

    def test_deprecated_train_and_infer_gate_on_body_workspace_id(self) -> None:
        for subject, payload in (
            ("rpc.analytics.train", {"cutoff_tournament_id": 5, "workspace_id": 1}),
            ("rpc.analytics.infer", {"tournament_id": 5, "workspace_id": 1}),
        ):
            with self.subTest(subject=subject):
                envelope = self._call(subject, {"identity": _identity(global_update=True), "payload": payload})

                self.assertFalse(envelope["ok"])
                self.assertEqual(envelope["error"]["code"], "forbidden")
                self.assertEqual(envelope["error"]["message"], "workspace_not_verified")
                self.assertEqual(self.broker.published, [])

    def test_deprecated_train_publishes_for_a_trusted_workspace(self) -> None:
        envelope = self._call(
            "rpc.analytics.train",
            {"identity": _identity(global_update=True), "payload": {"cutoff_tournament_id": 5, "workspace_id": 3}},
        )

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(len(self.broker.published), 1)
