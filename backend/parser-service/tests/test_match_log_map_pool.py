"""Configured encounter pools reject logs before roster or match writes."""

from __future__ import annotations

import importlib
import os
import sys
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))
os.environ["DEBUG"] = "true"

flows = importlib.import_module("src.services.match_logs.flows")


def config(*, items=(), slots=(), stage_id=None, round=None):
    return SimpleNamespace(
        mode=flows.enums.MapVetoMode.SLOTS if slots else flows.enums.MapVetoMode.POOL,
        stage_id=stage_id,
        round=round,
        items=[SimpleNamespace(item_id=item) for item in items],
        slots=[
            SimpleNamespace(items=[SimpleNamespace(item_id=item) for item in candidates], reserve_item_id=reserve)
            for candidates, reserve in slots
        ],
    )


class MatchLogMapPoolTests(IsolatedAsyncioTestCase):
    async def ingest(self, configs, *, map_name="Илиос", attached_pair=(1, 2)):
        writes = []
        encounter = SimpleNamespace(
            id=7, tournament_id=1, stage_id=4, round=2,
            home_team_id=attached_pair[0], away_team_id=attached_pair[1],
        )
        match = SimpleNamespace(
            id=5, time=10.0, home_score=0, away_score=2, map_id=3,
            home_team_id=1, away_team_id=2, log_name="old.log", log_record_id=9,
        )
        session = SimpleNamespace(
            get=AsyncMock(return_value=encounter),
            commit=AsyncMock(side_effect=lambda: writes.append("commit")),
            rollback=AsyncMock(),
        )
        processor = flows.MatchLogProcessor(
            SimpleNamespace(id=1, name="Cup"), "new.log",
            [f"0,match_start,0,{map_name},Control,Home,Away", "0,match_end,100,Home,2,0"],
            SimpleNamespace(), log_record_id=10, attached_encounter_id=7,
        )
        home, away = SimpleNamespace(id=1), SimpleNamespace(id=2)
        processor._preload_data = AsyncMock()
        processor.find_teams_by_players = AsyncMock(return_value=((home, []), (away, [])))
        processor.process_teams = AsyncMock(
            side_effect=lambda *args: writes.append("roster") or ((home, {}), (away, {}))
        )
        processor.process_kills = AsyncMock(return_value=[])
        processor.process_events = AsyncMock(return_value=[])
        processor.create_stats = AsyncMock(return_value=[])

        async def resolve(_session, name, _mode, **kwargs):
            return SimpleNamespace(id={"Ilios": 3, "Илиос": 3}[name], name="Ilios")

        with ExitStack() as stack:
            stack.enter_context(patch.object(flows.map_flows, "get_by_name_or_alias_and_gamemode", resolve))
            stack.enter_context(patch.object(flows._pick_ban_config_repo, "list_by_tournament", AsyncMock(return_value=configs)))
            stack.enter_context(patch.object(flows.encounter_service, "get_match_by_encounter_and_map", AsyncMock(return_value=match)))
            stack.enter_context(patch.object(flows._match_repo, "create", AsyncMock(side_effect=lambda *args: writes.append("match"))))
            for repo in (flows._stats_repo, flows._events_repo, flows._kill_feed_repo):
                stack.enter_context(patch.object(repo, "delete_for_match", AsyncMock(side_effect=lambda *args: writes.append("delete"))))
            stack.enter_context(patch.object(flows, "_bulk_insert", AsyncMock()))
            stack.enter_context(patch.object(flows, "_enqueue_match_log_tournament_events", AsyncMock()))
            try:
                result = await processor.start(session)
            except flows.errors.ApiHTTPException as exc:
                return exc, match, writes
        return result, match, writes

    async def test_alias_outside_effective_round_pool_preserves_existing_match_and_roster(self):
        for name in ("Ilios", "Илиос"):
            with self.subTest(name=name):
                result, match, writes = await self.ingest(
                    [config(items=(3,)), config(items=(8,), stage_id=4, round=2)], map_name=name,
                )
                self.assertIsInstance(result, flows.errors.ApiHTTPException)
                self.assertEqual(400, result.status_code)
                self.assertEqual("map_not_in_pool", result.detail[0]["code"])
                self.assertEqual((10.0, 0, 2, "old.log", 9),
                                 (match.time, match.home_score, match.away_score, match.log_name, match.log_record_id))
                self.assertEqual([], writes)

    async def test_configured_candidates_and_reserves_accept_canonical_alias(self):
        for pool in (config(items=(3,)), config(slots=(((3, 8), None),)), config(slots=(((8, 9), 3),))):
            with self.subTest(pool=pool):
                result, match, writes = await self.ingest([pool])
                self.assertIs(result, match)
                self.assertEqual((100.0, 2, 0, "new.log", 10),
                                 (match.time, match.home_score, match.away_score, match.log_name, match.log_record_id))
                self.assertIn("roster", writes)
                self.assertIn("commit", writes)

    async def test_no_pool_is_unrestricted_and_empty_template_keeps_parent_pool(self):
        for configs in ([], [config()], [config(items=(3,)), config(stage_id=4, round=2)]):
            with self.subTest(configs=configs):
                result, match, writes = await self.ingest(configs)
                self.assertIs(result, match)
                self.assertEqual("new.log", match.log_name)
                self.assertIn("commit", writes)
        result, match, writes = await self.ingest([config(items=(8,)), config(stage_id=4, round=2)])
        self.assertIsInstance(result, flows.errors.ApiHTTPException)
        self.assertEqual("map_not_in_pool", result.detail[0]["code"])
        self.assertEqual("old.log", match.log_name)
        self.assertEqual([], writes)

    async def test_pool_validation_does_not_bypass_explicit_encounter_binding(self):
        result, match, writes = await self.ingest([config(items=(3,))], attached_pair=(1, 99))
        self.assertIsInstance(result, flows.errors.ApiHTTPException)
        self.assertEqual("attached_encounter_mismatch", result.detail[0]["code"])
        self.assertEqual("old.log", match.log_name)
        self.assertEqual([], writes)
