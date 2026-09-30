"""Who may PATCH an encounter: the score side versus the bracket's structure.

``match.result`` (the referee's grant) moves a score, a status, a closeness; the
teams, stage, round, best-of and schedule ARE the bracket and stay behind
``match.update``. A payload mixing the two needs both -- otherwise a score edit
would carry a bracket edit past the referee, and a structural edit would carry a
score past staff who hold only ``update``.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest import IsolatedAsyncioTestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from shared.rpc.crud import CrudDispatcher  # noqa: E402
from tests._rpc_fakes import FakeSessionMaker, make_identity  # noqa: E402

registry = importlib.import_module("src.services.admin.registry")

WORKSPACE_ID = 3
ENCOUNTER_ID = 11


def _identity(*actions: str) -> dict[str, Any]:
    return make_identity(
        workspaces=[
            {
                "workspace_id": WORKSPACE_ID,
                "rbac_roles": [],
                "rbac_permissions": [{"resource": "match", "action": action} for action in actions],
            }
        ]
    )


class EncounterUpdatePermissionSplitTests(IsolatedAsyncioTestCase):
    async def _patch(self, identity: dict[str, Any], payload: dict[str, Any]) -> tuple[dict[str, Any], list]:
        written: list[dict[str, Any]] = []

        async def workspace_of(_session: Any, _encounter_id: int) -> int:
            return WORKSPACE_ID

        async def update(_session: Any, encounter_id: int, body: Any, _data: Any) -> SimpleNamespace:
            written.append(body.model_dump(exclude_unset=True))
            return SimpleNamespace(id=encounter_id)

        async def serialize(_session: Any, obj: Any) -> dict[str, Any]:
            return {"id": obj.id}

        # The real entity -- its schema and its field split -- with only the
        # database-facing hooks replaced.
        config = dataclasses.replace(
            registry.REGISTRY["encounter"],
            resolve_ws_from_id=workspace_of,
            service_update=update,
            serializer=serialize,
        )
        dispatcher = CrudDispatcher({"encounter": config}, FakeSessionMaker())
        envelope = await dispatcher.do_update(
            {"entity": "encounter", "id": ENCOUNTER_ID, "identity": identity, "payload": payload}
        )
        return envelope, written

    async def test_result_grant_moves_the_score_side(self) -> None:
        payload = {"home_score": 2, "away_score": 1, "status": "live", "closeness": 0.6}
        envelope, written = await self._patch(_identity("result"), payload)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([payload], written)

    async def test_result_grant_cannot_touch_the_bracket(self) -> None:
        for payload in ({"best_of": 5}, {"home_team_id": 9}, {"home_score": 2, "round": 3}):
            with self.subTest(payload=payload):
                envelope, written = await self._patch(_identity("result"), payload)

                self.assertFalse(envelope["ok"], envelope)
                self.assertEqual("forbidden", envelope["error"]["code"])
                self.assertIn("match.update", envelope["error"]["message"])
                self.assertEqual([], written)

    async def test_update_grant_alone_cannot_carry_a_score(self) -> None:
        envelope, written = await self._patch(_identity("update"), {"best_of": 5, "home_score": 2})

        self.assertFalse(envelope["ok"], envelope)
        self.assertIn("match.result", envelope["error"]["message"])
        self.assertEqual([], written)

    async def test_both_grants_edit_the_whole_encounter(self) -> None:
        payload = {"best_of": 5, "home_score": 2, "scheduled_at": None}
        envelope, written = await self._patch(_identity("update", "result"), payload)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual([payload], written)
