"""A corrected map report must move the series score with it.

``submit_map_report`` rewrites an existing ``source=captain_report`` match row
when both captains agree on a new score, but the encounter's own
``home_score``/``away_score`` were frozen behind ``if not already_played`` --
so a 2:0 corrected to 0:2 left the series reading 1:0 for the wrong team, and
the ``series_decided`` gate behind it read the stale number too. A parsed log
row is never rewritten, so its contribution to the series must not move either.
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

map_report = importlib.import_module("src.services.encounter.map_report")
enums = importlib.import_module("shared.core.enums")

HOME_TEAM = 1
AWAY_TEAM = 2
MAP_ID = 77


def _report(team_id: int, home: int, away: int) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id=10,
        map_id=MAP_ID,
        map_index=1,
        team_id=team_id,
        home_score=home,
        away_score=away,
        reporter_user_id=None,
    )


class CorrectedCaptainReport(IsolatedAsyncioTestCase):
    async def _resubmit(self, *, match_source: str):
        """Both captains already agreed 2:0 for home; the away captain has since
        corrected to 0:2 and the home captain now files the same correction."""
        encounter = SimpleNamespace(
            id=10,
            tournament_id=1,
            home_team_id=HOME_TEAM,
            away_team_id=AWAY_TEAM,
            home_score=1,
            away_score=0,
            best_of=3,
        )
        match = SimpleNamespace(
            id=5,
            map_index=1,
            home_score=2,
            away_score=0,
            source=match_source,
        )
        rows = [_report(HOME_TEAM, 2, 0), _report(AWAY_TEAM, 0, 2)]
        session = SimpleNamespace(
            add=lambda _o: None,
            flush=AsyncMock(),
            commit=AsyncMock(),
            execute=AsyncMock(),
        )

        service = map_report.MapReportService(
            report_repo=SimpleNamespace(
                list_for_encounter=AsyncMock(return_value=rows),
                list_for_map_slot=AsyncMock(return_value=rows),
            ),
            entry_repo=SimpleNamespace(list_by_session=AsyncMock(return_value=[])),
        )

        with (
            patch.object(map_report, "is_encounter_live", AsyncMock(return_value=True)),
            patch.object(map_report, "is_scrim_container", AsyncMock(return_value=False)),
            patch.object(map_report, "emit_pick_ban_update", AsyncMock()),
            patch.object(map_report, "emit", AsyncMock()),
            patch.object(map_report.pick_ban_session_service, "get_pick_ban_session", AsyncMock(return_value=None)),
            patch.object(map_report.pick_ban_session_service, "find_series_match", AsyncMock(return_value=match)),
        ):
            result = await service.submit_map_report(
                session,
                encounter,
                map_id=MAP_ID,
                team_id=HOME_TEAM,
                reporter_user_id=99,
                home_score=0,
                away_score=2,
            )
        return encounter, match, result

    async def test_captain_report_correction_moves_series_score(self):
        encounter, match, result = await self._resubmit(match_source=enums.MatchSource.CAPTAIN_REPORT.value)

        self.assertTrue(result["resolved"])
        self.assertEqual((0, 2), (match.home_score, match.away_score))
        # Pre-fix this reads (1, 0): the row was corrected, the series was not.
        self.assertEqual((0, 1), (encounter.home_score, encounter.away_score))

    async def test_parsed_log_row_leaves_series_score_alone(self):
        encounter, match, _ = await self._resubmit(match_source=enums.MatchSource.LOG_PARSER.value)

        self.assertEqual((2, 0), (match.home_score, match.away_score))
        self.assertEqual((1, 0), (encounter.home_score, encounter.away_score))
