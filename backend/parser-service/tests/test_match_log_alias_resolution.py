"""Log names resolve through catalog aliases, and misses reach the queue.

The three hardcoded translation dicts are gone; what replaced them is a hero
cache folded from `hero.aliases`, a single alias-aware map lookup, and two
different miss paths — inline for the hard map/gamemode 404, batched for the soft
per-kill-event hero miss. Each of those is pinned here.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pandas as pd

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ["DEBUG"] = "true"

flows = importlib.import_module("src.services.match_logs.flows")
map_flows = importlib.import_module("src.services.map.flows")
map_service_module = importlib.import_module("src.services.map.service")
map_service = map_service_module.map_service
shared_enums = importlib.import_module("shared.core.enums")
errors = flows.errors


def _processor() -> object:
    processor = flows.MatchLogProcessor.__new__(flows.MatchLogProcessor)
    processor.heroes_map = {}
    processor.hero_misses = set()
    processor.log_record_id = 11
    processor.attached_encounter_id = None
    return processor


class HeroAliasResolutionTests(IsolatedAsyncioTestCase):
    async def test_preload_folds_db_aliases_into_the_hero_cache(self) -> None:
        ana = SimpleNamespace(name="Ana", aliases=["Ана", "アナ"])
        processor = _processor()

        with patch.object(flows.hero_service, "get_all", AsyncMock(return_value=([ana], 1))):
            await processor._preload_data(Mock())

        self.assertIs(ana, processor.heroes_map["Ana"])
        self.assertIs(ana, processor.heroes_map["Ана"])
        self.assertIs(ana, processor.heroes_map["アナ"])

    async def test_a_canonical_name_is_never_shadowed_by_another_heros_alias(self) -> None:
        # Somebody attaches "Ana" as an alias of Ashe by mistake; Ana must win.
        ana = SimpleNamespace(name="Ana", aliases=[])
        ashe = SimpleNamespace(name="Ashe", aliases=["Ana", "Эш"])
        processor = _processor()

        with patch.object(flows.hero_service, "get_all", AsyncMock(return_value=([ana, ashe], 2))):
            await processor._preload_data(Mock())

        self.assertIs(ana, processor.heroes_map["Ana"])
        self.assertIs(ashe, processor.heroes_map["Эш"])

    def test_the_canonical_name_never_needs_an_alias(self) -> None:
        processor = _processor()
        processor.heroes_map = {"Ana": SimpleNamespace(name="Ana")}

        self.assertEqual("Ana", processor.get_hero("Ana").name)
        self.assertEqual(set(), processor.hero_misses)

    def test_an_unknown_hero_is_queued_as_a_miss_and_still_raises(self) -> None:
        processor = _processor()

        with self.assertRaises(errors.ApiHTTPException):
            processor.get_hero("Хтоническая Сущность")

        # The three call sites swallow the exception, so the queue is the only
        # place this data loss becomes visible.
        self.assertEqual({"Хтоническая Сущность"}, processor.hero_misses)

    def test_repeated_misses_collapse_into_one_queued_name(self) -> None:
        processor = _processor()

        for _ in range(3):
            with self.assertRaises(errors.ApiHTTPException):
                processor.get_hero("Кулак Смерти")

        self.assertEqual({"Кулак Смерти"}, processor.hero_misses)


class MapAliasResolutionTests(IsolatedAsyncioTestCase):
    async def test_a_resolved_map_records_nothing(self) -> None:
        resolved = SimpleNamespace(id=3, name="Ilios")
        record_misses = AsyncMock()

        with (
            patch.object(map_service, "get_by_name_or_alias_and_gamemode", AsyncMock(return_value=resolved)),
            patch.object(map_service_module.catalog_aliases, "record_misses", record_misses),
        ):
            found = await map_flows.get_by_name_or_alias_and_gamemode(Mock(), "Илиос", "Контроль", log_record_id=11)

        self.assertIs(resolved, found)
        record_misses.assert_not_awaited()

    async def test_an_unknown_map_records_both_misses_before_raising(self) -> None:
        recorded: list[tuple] = []

        async def fake_record(entity_type, names, *, log_record_id=None) -> None:
            recorded.append((entity_type, sorted(names), log_record_id))

        with (
            patch.object(map_service, "get_by_name_or_alias_and_gamemode", AsyncMock(return_value=None)),
            patch.object(map_service_module.catalog_aliases, "record_misses", fake_record),
            self.assertRaises(errors.ApiHTTPException),
        ):
            await map_flows.get_by_name_or_alias_and_gamemode(Mock(), "Хогвартс", "Контроль", log_record_id=11)

        # Both names, because a failed join cannot say which one was unknown.
        self.assertEqual(
            [
                (shared_enums.CatalogEntityType.map, ["Хогвартс"], 11),
                (shared_enums.CatalogEntityType.gamemode, ["Контроль"], 11),
            ],
            recorded,
        )

    async def test_get_map_passes_the_raw_log_names_through_untranslated(self) -> None:
        processor = _processor()
        processor.df = pd.DataFrame()
        processor._get_rows = Mock(return_value=pd.DataFrame({"data": [["Илиос", "Контроль"]]}))
        resolve = AsyncMock(return_value=SimpleNamespace(id=3, name="Ilios"))

        with patch.object(flows.map_flows, "get_by_name_or_alias_and_gamemode", resolve):
            await processor.get_map(Mock())

        resolve.assert_awaited_once()
        args, kwargs = resolve.await_args
        self.assertEqual(("Илиос", "Контроль"), args[1:])
        self.assertEqual(11, kwargs["log_record_id"])


class HeroMissFlushTests(IsolatedAsyncioTestCase):
    async def test_start_flushes_the_hero_misses_once_after_stats_and_before_commit(self) -> None:
        calls: list[tuple] = []

        async def fake_record(entity_type, names, *, log_record_id=None) -> None:
            calls.append(("record_misses", entity_type, sorted(names), log_record_id))

        session = MagicMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock(side_effect=lambda: calls.append(("commit",)))

        team = SimpleNamespace(id=1)
        match_model = SimpleNamespace(
            id=5, time=0.0, home_score=0, away_score=0, map_id=0, home_team_id=0, away_team_id=0, log_name=""
        )

        processor = _processor()
        processor.filename = "match.log"
        processor.tournament = SimpleNamespace(id=1, name="Spring Cup")
        processor.df = pd.DataFrame({"event_type": ["match_end"]})
        processor.hero_misses = {"Кхтон", "Ана"}
        processor.validate = AsyncMock(return_value=True)
        processor._preload_data = AsyncMock()
        processor.process_teams = AsyncMock(return_value=((team, {}), (team, {})))
        processor.get_map = AsyncMock(return_value=SimpleNamespace(id=3, name="Ilios"))
        processor.get_match_score_and_time = Mock(return_value=(1.0, 2, 1))
        processor.process_kills = AsyncMock(return_value=[])
        processor.process_events = AsyncMock(return_value=[])
        processor.create_stats = AsyncMock(side_effect=lambda *a, **kw: calls.append(("create_stats",)) or [])

        with (
            patch.object(flows.encounter_flows, "resolve_for_log", AsyncMock(return_value=SimpleNamespace(id=9))),
            patch.object(
                flows.encounter_service, "get_match_by_encounter_and_map", AsyncMock(return_value=match_model)
            ),
            patch.object(flows, "_enqueue_match_log_tournament_events", AsyncMock()),
            patch.object(flows.catalog_aliases, "record_misses", fake_record),
        ):
            await processor.start(session)

        self.assertEqual(
            [
                ("create_stats",),
                ("record_misses", shared_enums.CatalogEntityType.hero, ["Ана", "Кхтон"], 11),
                ("commit",),
            ],
            calls,
        )

    async def test_start_skips_the_flush_when_every_hero_resolved(self) -> None:
        record_misses = AsyncMock()

        session = MagicMock()
        session.execute = AsyncMock()
        session.flush = AsyncMock()
        session.commit = AsyncMock()

        team = SimpleNamespace(id=1)
        match_model = SimpleNamespace(
            id=5, time=0.0, home_score=0, away_score=0, map_id=0, home_team_id=0, away_team_id=0, log_name=""
        )

        processor = _processor()
        processor.filename = "match.log"
        processor.tournament = SimpleNamespace(id=1, name="Spring Cup")
        processor.df = pd.DataFrame({"event_type": ["match_end"]})
        processor.validate = AsyncMock(return_value=True)
        processor._preload_data = AsyncMock()
        processor.process_teams = AsyncMock(return_value=((team, {}), (team, {})))
        processor.get_map = AsyncMock(return_value=SimpleNamespace(id=3, name="Ilios"))
        processor.get_match_score_and_time = Mock(return_value=(1.0, 2, 1))
        processor.process_kills = AsyncMock(return_value=[])
        processor.process_events = AsyncMock(return_value=[])
        processor.create_stats = AsyncMock(return_value=[])

        with (
            patch.object(flows.encounter_flows, "resolve_for_log", AsyncMock(return_value=SimpleNamespace(id=9))),
            patch.object(
                flows.encounter_service, "get_match_by_encounter_and_map", AsyncMock(return_value=match_model)
            ),
            patch.object(flows, "_enqueue_match_log_tournament_events", AsyncMock()),
            patch.object(flows.catalog_aliases, "record_misses", record_misses),
        ):
            await processor.start(session)

        record_misses.assert_not_awaited()
