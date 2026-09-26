"""Which encounter a parsed log is filed under.

Two teams can meet more than once in a tournament (groups then playoffs, a
double-elimination rematch). The resolver must never pick one of those
silently: the uploader's attachment decides, a re-parse keeps its earlier
choice, and anything else is refused.
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
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

encounter_flows = importlib.import_module("src.services.encounter.flows")

GROUP = SimpleNamespace(id=1, home_team_id=10, away_team_id=20)
PLAYOFF = SimpleNamespace(id=2, home_team_id=20, away_team_id=10)
OTHER_PAIR = SimpleNamespace(id=3, home_team_id=10, away_team_id=30)


class _Session:
    async def get(self, _model, ident):
        return {e.id: e for e in (GROUP, PLAYOFF, OTHER_PAIR)}.get(ident)


class ResolveForLogTests(IsolatedAsyncioTestCase):
    async def _resolve(self, candidates, *, previous=(), attached=None):
        with (
            patch.object(encounter_flows.service, "list_by_teams", AsyncMock(return_value=list(candidates))),
            patch.object(encounter_flows.service, "encounter_ids_with_log", AsyncMock(return_value=set(previous))),
        ):
            return await encounter_flows.resolve_for_log(
                _Session(), 10, 20, log_name="m.txt", attached_encounter_id=attached
            )

    async def _refusal(self, candidates, **kwargs) -> tuple[int, str]:
        with self.assertRaises(encounter_flows.errors.ApiHTTPException) as ctx:
            await self._resolve(candidates, **kwargs)
        return ctx.exception.status_code, ctx.exception.detail[0]["code"]

    async def test_a_pair_that_meets_once_resolves_to_that_encounter(self) -> None:
        self.assertIs(GROUP, await self._resolve([GROUP]))

    async def test_a_pair_that_meets_twice_is_refused_rather_than_guessed(self) -> None:
        self.assertEqual((409, "encounter_ambiguous"), await self._refusal([GROUP, PLAYOFF]))

    async def test_a_reparse_keeps_the_encounter_the_same_file_was_filed_under(self) -> None:
        self.assertIs(PLAYOFF, await self._resolve([GROUP, PLAYOFF], previous={PLAYOFF.id}))

    async def test_the_attached_encounter_wins_over_an_ambiguous_pair(self) -> None:
        # Flipped orientation: the log's home side is the encounter's away side.
        self.assertIs(PLAYOFF, await self._resolve([GROUP, PLAYOFF], attached=PLAYOFF.id))

    async def test_an_attached_encounter_between_other_teams_is_refused(self) -> None:
        self.assertEqual((400, "attached_encounter_mismatch"), await self._refusal([GROUP], attached=OTHER_PAIR.id))
