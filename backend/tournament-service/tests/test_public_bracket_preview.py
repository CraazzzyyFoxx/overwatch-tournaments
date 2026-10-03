"""The public bracket preview answers only for the tournament in its path.

``/tournaments/{id}/stages/{stage_id}/bracket-preview`` gates ``{id}`` like every
public tournament read. The stage is a second, independent id: without its own
check, a visible tournament's path would draw a hidden tournament's stage.
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

from tests._rpc_fakes import CapturingBroker, FakeSessionMaker  # noqa: E402

reads = importlib.import_module("src.rpc.reads")
helpers = importlib.import_module("src.rpc._helpers")

SUBJECT = "rpc.tournament.stage_bracket_preview_public"
TOURNAMENT_ID = 117
STAGE_ID = 253
SKELETON = {"matches": [{"local_id": 1, "round": 1, "sources": []}]}


class PublicBracketPreview(IsolatedAsyncioTestCase):
    async def _call(self, *, stage_tournament_id: int) -> tuple[dict, AsyncMock, AsyncMock]:
        broker = CapturingBroker()
        reads.register(broker, SimpleNamespace(exception=lambda *a, **k: None))
        viewable = AsyncMock()
        preview = AsyncMock(return_value=SKELETON)
        self.enterContext(patch.object(helpers.db, "async_session_maker", FakeSessionMaker()))
        self.enterContext(patch.object(reads, "ensure_tournament_viewable", viewable))
        self.enterContext(
            patch.object(reads.admin_stage_service, "get_tournament_id", AsyncMock(return_value=stage_tournament_id))
        )
        self.enterContext(patch.object(reads.admin_stage_service, "get_bracket_preview", preview))

        envelope = await broker.handlers[SUBJECT]({"id": TOURNAMENT_ID, "stage_id": STAGE_ID}, None)
        return envelope, viewable, preview

    async def test_draws_the_stage_of_the_tournament_in_the_path(self) -> None:
        envelope, viewable, preview = await self._call(stage_tournament_id=TOURNAMENT_ID)

        self.assertTrue(envelope["ok"], envelope)
        self.assertEqual(SKELETON, envelope["data"])
        self.assertEqual(TOURNAMENT_ID, viewable.await_args.args[2])
        preview.assert_awaited_once()

    async def test_a_stage_of_another_tournament_is_not_found(self) -> None:
        envelope, _viewable, preview = await self._call(stage_tournament_id=TOURNAMENT_ID + 1)

        self.assertFalse(envelope["ok"], envelope)
        self.assertEqual("not_found", envelope["error"]["code"])
        preview.assert_not_awaited()
