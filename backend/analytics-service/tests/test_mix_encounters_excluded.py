"""The rating replay reads tournament encounters only; a mix round in the same workspace is not one (D77)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "analytics-service"))

from shared.tests.encounter_writer_case import EncounterWriterCase  # noqa: E402

analytics_service = importlib.import_module("src.services.analytics.service")


class MixEncountersExcludedTests(EncounterWriterCase):
    async def test_the_rating_replay_source_leaves_the_mix_round_out(self) -> None:
        async with self.Session() as s:
            await self.mix_encounter(s)
            await s.commit()
        async with self.Session() as s:
            rows = await analytics_service.AnalyticsService().get_matches_for_tournaments(
                s, [self.ids["t"]], workspace_id=self.ids["ws"], discipline="overwatch"
            )
        self.assertEqual([self.ids["e"]], [row.id for row in rows])
