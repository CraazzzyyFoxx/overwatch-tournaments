"""Preview matches refuse gameplay writes; organizers may still swap seed slots.

``generate_encounters`` can lay a playoff out before its stage is activated
(``Stage.is_published=False``). Captain reports, map reports, the pick-ban room,
readiness, map choices and admin results must wait for publication.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker, make_identity  # noqa: E402

admin_misc = importlib.import_module("src.rpc.admin_misc")
public_rpc = importlib.import_module("src.rpc.public_rpc")
helpers = importlib.import_module("src.rpc._helpers")

ENCOUNTER_ID = 31
STAGE_ID = 5
ADMIN = make_identity(
    workspaces=[
        {
            "workspace_id": 1,
            "rbac_roles": [],
            "rbac_permissions": [{"resource": "match", "action": "result"}, {"resource": "match", "action": "update"}],
        }
    ]
)


def _handler(module, subject: str):
    broker = CapturingBroker()
    module.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
    return broker.handlers[subject]


class PreviewBracketWrites(IsolatedAsyncioTestCase):
    def _stage(self, *, published: bool) -> None:
        encounter = SimpleNamespace(id=ENCOUNTER_ID, stage_id=STAGE_ID, home_team_id=1, away_team_id=2)
        stage = SimpleNamespace(is_published=published)
        session = SimpleNamespace(add=lambda _row: None, get=AsyncMock(return_value=stage))
        self.enterContext(patch.object(helpers.db, "async_session_maker", FakeSessionMaker(session)))
        self.enterContext(
            patch.object(public_rpc.captain_service, "_load_encounter", AsyncMock(return_value=encounter))
        )
        self.enterContext(
            patch.object(
                admin_misc.enc_service.encounter_service.encounter_repo, "get", AsyncMock(return_value=encounter)
            )
        )
        self.enterContext(patch.object(admin_misc.auth, "get_encounter_workspace_id", AsyncMock(return_value=1)))

    async def test_gameplay_writes_are_refused_while_the_stage_is_a_preview(self) -> None:
        cases = [
            (public_rpc, "rpc.tournament.captain_ready", {}, public_rpc.pick_ban_session_service, "mark_ready"),
            (
                public_rpc,
                "rpc.tournament.captain_select_game_map",
                {"game_id": 77, "payload": {"map_id": 12}},
                public_rpc.encounter_game_service,
                "select_map",
            ),
            (
                admin_misc,
                "rpc.tournament.encounter_set_result",
                {"payload": {"home_score": 3, "away_score": 1}},
                admin_misc.captain_service,
                "set_encounter_result",
            ),
        ]
        self._stage(published=False)
        for module, subject, extra, service, method in cases:
            with self.subTest(subject), patch.object(service, method, AsyncMock()) as write:
                envelope = await _handler(module, subject)({"identity": ADMIN, "id": ENCOUNTER_ID, **extra}, None)

                self.assertFalse(envelope["ok"], envelope)
                self.assertEqual("conflict", envelope["error"]["code"])
                write.assert_not_awaited()

    async def test_a_published_stage_takes_the_captains_readiness(self) -> None:
        self._stage(published=True)
        self.enterContext(
            patch.object(public_rpc.captain_service, "resolve_captain_identity", AsyncMock(return_value=("away", 9, 2)))
        )
        ready = self.enterContext(
            patch.object(
                public_rpc.pick_ban_session_service, "mark_ready", AsyncMock(return_value={"home": False, "away": True})
            )
        )

        envelope = await _handler(public_rpc, "rpc.tournament.captain_ready")(
            {"identity": ADMIN, "id": ENCOUNTER_ID}, None
        )

        self.assertTrue(envelope["ok"], envelope)
        ready.assert_awaited_once()
