from __future__ import annotations

import importlib
import inspect
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from cashews.key import get_cache_key

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


encounter_flows = importlib.import_module("src.services.encounter.flows")
encounter_schemas = importlib.import_module("src.schemas.encounter")


class EncounterCacheKeyTests(IsolatedAsyncioTestCase):
    async def test_encounter_list_cache_separates_search_queries(self) -> None:
        unique_prefix = str(uuid4())
        first = encounter_schemas.EncounterSearchParams(
            query=f"{unique_prefix}-first",
            fields=["name"],
        )
        second = encounter_schemas.EncounterSearchParams(
            query=f"{unique_prefix}-second",
            fields=["name"],
        )
        load_encounters = AsyncMock(return_value=([], 0))

        with patch.object(encounter_flows.flows_service.encounters, "get_all_encounters", load_encounters):
            await encounter_flows.flows_service.encounters_page(SimpleNamespace(), first)
            await encounter_flows.flows_service.encounters_page(SimpleNamespace(), second)

        self.assertEqual(load_encounters.await_count, 2)

    def test_every_sql_changing_param_reaches_every_key(self) -> None:
        # The key once left the game out: whichever game asked first had its page served to every other game.
        variants = [
            encounter_schemas.EncounterSearchParams(discipline="overwatch"),
            encounter_schemas.EncounterSearchParams(discipline="deadlock"),
            encounter_schemas.EncounterSearchParams(),
            encounter_schemas.EncounterSearchParams(slot_count=8),
            encounter_schemas.EncounterSearchParams(is_final=True),
            encounter_schemas.EncounterSearchParams(is_final=False),
            encounter_schemas.EncounterSearchParams(is_upset=True),
        ]
        for template, function in (
            (encounter_flows.ENCOUNTERS_CACHE_KEY, encounter_flows.EncounterFlowsService.encounters_page),
            (
                encounter_flows.ENCOUNTERS_OVERVIEW_CACHE_KEY,
                encounter_flows.EncounterFlowsService.overview_page,
            ),
            (
                encounter_flows.ENCOUNTERS_INSIGHTS_CACHE_KEY,
                encounter_flows.EncounterFlowsService.insights_page,
            ),
        ):
            keys = {
                get_cache_key(
                    inspect.unwrap(function),
                    template,
                    kwargs={"workspace_id": None, "params": params, "viewer_auth_user_id": None},
                )
                for params in variants
            }
            self.assertEqual(len(variants), len(keys), template)
