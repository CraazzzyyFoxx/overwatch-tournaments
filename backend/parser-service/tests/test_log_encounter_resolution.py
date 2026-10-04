"""Which encounter a parsed log is filed under.

Two teams can meet more than once in a tournament (groups then playoffs, a
double-elimination rematch). The resolver must never pick one of those
silently: the uploader's attachment decides, a re-parse keeps its earlier
choice, the log's map narrows by round pool and by the maps each series
already holds, and anything still ambiguous is refused.
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
MapVetoMode = importlib.import_module("shared.core.enums").MapVetoMode

GROUP = SimpleNamespace(id=1, home_team_id=10, away_team_id=20, stage_id=100, round=4)
PLAYOFF = SimpleNamespace(id=2, home_team_id=20, away_team_id=10, stage_id=200, round=-3)
OTHER_PAIR = SimpleNamespace(id=3, home_team_id=10, away_team_id=30, stage_id=100, round=1)

RIALTO, LIJIANG, ROUTE_66 = 28, 13, 26


def round_pool(stage_id, round, *maps):
    return SimpleNamespace(
        mode=MapVetoMode.POOL,
        stage_id=stage_id,
        round=round,
        items=[SimpleNamespace(item_id=item) for item in maps],
        slots=[],
    )


# Both rounds offer Lijiang; only the group offers Rialto, only the playoff Route 66.
POOLS = [round_pool(100, 4, RIALTO, LIJIANG), round_pool(200, -3, ROUTE_66, LIJIANG)]


class _Session:
    async def get(self, _model, ident):
        return {e.id: e for e in (GROUP, PLAYOFF, OTHER_PAIR)}.get(ident)


class ResolveForLogTests(IsolatedAsyncioTestCase):
    async def _resolve(self, candidates, *, previous=(), played=(), attached=None, map_id=LIJIANG, pools=POOLS):
        with (
            patch.object(encounter_flows.service, "list_by_teams", AsyncMock(return_value=list(candidates))),
            patch.object(encounter_flows.service, "encounter_ids_with_log", AsyncMock(return_value=set(previous))),
            patch.object(encounter_flows.service, "encounter_ids_with_map", AsyncMock(return_value=set(played))),
        ):
            return await encounter_flows.resolve_for_log(
                _Session(),
                10,
                20,
                log_name="m.txt",
                map_id=map_id,
                map_pools=pools,
                attached_encounter_id=attached,
            )

    async def _refusal(self, candidates, **kwargs) -> tuple[int, str]:
        with self.assertRaises(encounter_flows.errors.ApiHTTPException) as ctx:
            await self._resolve(candidates, **kwargs)
        return ctx.exception.status_code, ctx.exception.detail[0]["code"]

    async def test_a_pair_that_meets_once_resolves_to_that_encounter(self) -> None:
        self.assertIs(GROUP, await self._resolve([GROUP]))

    async def test_a_map_both_rounds_offer_and_neither_series_holds_is_refused_rather_than_guessed(self) -> None:
        self.assertEqual((409, "encounter_ambiguous"), await self._refusal([GROUP, PLAYOFF]))

    async def test_without_pools_a_pair_that_meets_twice_is_refused(self) -> None:
        self.assertEqual((409, "encounter_ambiguous"), await self._refusal([GROUP, PLAYOFF], pools=[]))

    async def test_the_round_pool_that_offers_the_map_decides(self) -> None:
        self.assertIs(PLAYOFF, await self._resolve([GROUP, PLAYOFF], map_id=ROUTE_66))
        self.assertIs(GROUP, await self._resolve([GROUP, PLAYOFF], map_id=RIALTO))

    async def test_a_series_already_holding_the_map_from_another_log_is_skipped(self) -> None:
        # Filing there would overwrite that match: matches are keyed by (encounter, map).
        self.assertIs(PLAYOFF, await self._resolve([GROUP, PLAYOFF], played={GROUP.id}))

    async def test_a_map_outside_every_pool_stays_ambiguous_for_the_pool_check_to_refuse(self) -> None:
        self.assertEqual((409, "encounter_ambiguous"), await self._refusal([GROUP, PLAYOFF], map_id=99))

    async def test_a_reparse_keeps_the_encounter_the_same_file_was_filed_under(self) -> None:
        self.assertIs(PLAYOFF, await self._resolve([GROUP, PLAYOFF], previous={PLAYOFF.id}))

    async def test_the_attached_encounter_wins_over_an_ambiguous_pair(self) -> None:
        # Flipped orientation: the log's home side is the encounter's away side.
        self.assertIs(PLAYOFF, await self._resolve([GROUP, PLAYOFF], attached=PLAYOFF.id))

    async def test_an_attached_encounter_between_other_teams_is_refused(self) -> None:
        self.assertEqual((400, "attached_encounter_mismatch"), await self._refusal([GROUP], attached=OTHER_PAIR.id))
