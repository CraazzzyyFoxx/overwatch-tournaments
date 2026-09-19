"""Node math for ``captain_report_activity`` and ``log_upload_count``.

Uses the SQLite fixture from ``test_scrim_achievement_isolation``.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_scrim_achievement_isolation as _scrim  # noqa: E402
from test_scrim_achievement_isolation import (  # noqa: E402
    LATER_TOURNAMENT_ID,
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    WORKSPACE_ID,
    _EngineTestCase,
)

# Importing the module is what registers the nodes.
importlib.import_module("src.services.achievement.engine.conditions.participation")  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models
sa = _scrim.sa

OTHER_WORKSPACE_ID = 2
OTHER_WORKSPACE_TOURNAMENT_ID = 42


class _ParticipationFixture(_scrim._Fixture):
    def foreign_tournament(self, tournament_id: int) -> None:
        """A tournament in a DIFFERENT workspace — nothing in it may ever count."""
        self.insert(
            models.Tournament.__table__,
            id=tournament_id,
            workspace_id=OTHER_WORKSPACE_ID,
            name=f"Foreign {tournament_id}",
            slug=f"foreign-{tournament_id}",
            is_hidden=False,
            is_league=False,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def captain_report(
        self,
        encounter_id: int,
        team_id: int,
        reporter_user_id: int | None,
        *,
        home_score: int = 2,
        away_score: int = 1,
    ) -> int:
        report_id = self._id()
        self.insert(
            models.EncounterCaptainReport.__table__,
            id=report_id,
            encounter_id=encounter_id,
            team_id=team_id,
            reporter_user_id=reporter_user_id,
            home_score=home_score,
            away_score=away_score,
            custom_fields_json={},
        )
        return report_id

    def map_report(
        self,
        encounter_id: int,
        team_id: int,
        reporter_user_id: int | None,
        *,
        map_id: int = 1,
        map_index: int = 1,
    ) -> int:
        row_id = self._id()
        self.insert(
            models.EncounterMapReport.__table__,
            id=row_id,
            encounter_id=encounter_id,
            map_id=map_id,
            map_index=map_index,
            team_id=team_id,
            reporter_user_id=reporter_user_id,
            home_score=1,
            away_score=0,
        )
        return row_id

    def map_code(self, report_id: int, *, map_index: int, code: str) -> int:
        row_id = self._id()
        self.insert(
            models.EncounterMapCode.__table__,
            id=row_id,
            report_id=report_id,
            map_index=map_index,
            map_id=None,
            code=code,
        )
        return row_id

    def readiness(self, encounter_id: int, side: str, ready_user_id: int | None) -> int:
        row_id = self._id()
        self.insert(
            models.EncounterReadiness.__table__,
            id=row_id,
            encounter_id=encounter_id,
            side=side,
            ready_user_id=ready_user_id,
        )
        return row_id

    def log_record(
        self,
        tournament_id: int,
        uploader_id: int | None,
        *,
        status: object = models.LogProcessingStatus.done,
        filename: str = "log.txt",
    ) -> int:
        row_id = self._id()
        self.insert(
            models.LogProcessingRecord.__table__,
            id=row_id,
            tournament_id=tournament_id,
            filename=filename,
            status=status,
            source=models.LogProcessingSource.upload,
            uploader_id=uploader_id,
            attempts=0,
        )
        return row_id


class _ParticipationCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _ParticipationFixture()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await _scrim.runner._resolve_grid(self.db.shim, WORKSPACE_ID, None)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            tournament=tournament,
            grid=grid,
            normalizer=None,
        )

    async def run_node(self, node_type: str, params: dict, tournament_id: int | None):  # noqa: ANN001, ANN201
        context = await self.context(tournament_id)
        result = await evaluator.evaluate(self.db.shim, {"type": node_type, "params": params}, context)
        return result, context


class CaptainReportActivityTests(_ParticipationCase):
    def _two_encounters(self) -> tuple[int, int, int, int]:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Reports", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(REAL_TOURNAMENT_ID, "away", captain_id=REAL_AWAY_USER)
        first = self.db.encounter(REAL_TOURNAMENT_ID, home, away)
        second = self.db.encounter(REAL_TOURNAMENT_ID, home, away)
        return home, away, first, second

    async def test_edited_report_still_counts_once_and_other_captain_is_separate(self) -> None:
        home, away, first, second = self._two_encounters()
        report = self.db.captain_report(first, home, REAL_HOME_USER)
        self.db.captain_report(second, home, REAL_HOME_USER)
        # The away captain's own report for the same encounter is theirs, not ours.
        self.db.captain_report(first, away, REAL_AWAY_USER)
        self.db.session.commit()
        # A captain re-submitting upserts the SAME row (unique on encounter+team):
        # the edit must not inflate the count to three.
        self.db.session.execute(
            sa.update(models.EncounterCaptainReport.__table__)
            .where(models.EncounterCaptainReport.__table__.c.id == report)
            .values(home_score=3, away_score=0)
        )
        self.db.session.commit()

        qualified, context = await self.run_node(
            "captain_report_activity",
            {"metric": "series_reported", "op": ">=", "value": 2},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, qualified)
        self.assertEqual(
            {"metric": "series_reported", "count": 2},
            context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID)],
        )

        # Three reports exist in total, but none of the captains filed three.
        too_many, _ = await self.run_node(
            "captain_report_activity",
            {"metric": "series_reported", "op": ">=", "value": 3},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual(set(), too_many)

    async def test_null_reporter_and_foreign_workspace_never_count(self) -> None:
        home, away, first, _second = self._two_encounters()
        self.db.captain_report(first, home, REAL_HOME_USER)
        # Sheet-imported / account-deleted report: no reporter to credit.
        self.db.captain_report(first, away, None)
        self.db.foreign_tournament(OTHER_WORKSPACE_TOURNAMENT_ID)
        foreign_team = self.db.team(OTHER_WORKSPACE_TOURNAMENT_ID, "foreign", captain_id=REAL_HOME_USER)
        foreign_encounter = self.db.encounter(OTHER_WORKSPACE_TOURNAMENT_ID, foreign_team, foreign_team)
        self.db.captain_report(foreign_encounter, foreign_team, REAL_HOME_USER)
        self.db.session.commit()

        qualified, _ = await self.run_node(
            "captain_report_activity",
            {"metric": "series_reported", "op": ">=", "value": 1},
            None,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, qualified)

    async def test_map_codes_are_credited_through_the_filers_own_report(self) -> None:
        home, away, first, _second = self._two_encounters()
        mine = self.db.captain_report(first, home, REAL_HOME_USER)
        theirs = self.db.captain_report(first, away, REAL_AWAY_USER)
        self.db.map_code(mine, map_index=1, code="AAAAA")
        self.db.map_code(mine, map_index=2, code="BBBBB")
        self.db.map_code(theirs, map_index=1, code="CCCCC")
        self.db.session.commit()

        qualified, context = await self.run_node(
            "captain_report_activity",
            {"metric": "map_codes", "op": ">=", "value": 2},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, qualified)
        self.assertEqual(2, context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID)]["count"])

    async def test_map_reports_and_readiness_count_their_own_rows(self) -> None:
        home, away, first, second = self._two_encounters()
        self.db.map_report(first, home, REAL_HOME_USER, map_id=1, map_index=1)
        self.db.map_report(first, home, REAL_HOME_USER, map_id=2, map_index=2)
        self.db.map_report(first, away, REAL_AWAY_USER, map_id=1, map_index=1)
        self.db.readiness(first, "home", REAL_HOME_USER)
        self.db.readiness(first, "away", REAL_AWAY_USER)
        self.db.readiness(second, "home", REAL_HOME_USER)
        self.db.session.commit()

        maps, _ = await self.run_node(
            "captain_report_activity",
            {"metric": "map_reports", "op": ">=", "value": 2},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, maps)

        ready, context = await self.run_node(
            "captain_report_activity",
            {"metric": "readiness", "op": ">=", "value": 1},
            REAL_TOURNAMENT_ID,
        )
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID), (REAL_AWAY_USER, REAL_TOURNAMENT_ID)},
            ready,
        )
        self.assertEqual(2, context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID)]["count"])


class LogUploadCountTests(_ParticipationCase):
    def _tournaments(self) -> None:
        for tournament_id in (REAL_TOURNAMENT_ID, LATER_TOURNAMENT_ID):
            self.db.tournament(
                tournament_id,
                name=f"T{tournament_id}",
                is_hidden=False,
                start=datetime(2026, tournament_id, 1, tzinfo=UTC),
            )

    async def test_failed_upload_is_ignored_unless_status_is_any(self) -> None:
        self._tournaments()
        self.db.log_record(REAL_TOURNAMENT_ID, REAL_HOME_USER)
        self.db.log_record(REAL_TOURNAMENT_ID, REAL_HOME_USER, status=models.LogProcessingStatus.failed)
        self.db.session.commit()

        done, _ = await self.run_node("log_upload_count", {"op": ">=", "value": 2}, None)
        self.assertEqual(set(), done)

        anything, context = await self.run_node("log_upload_count", {"op": ">=", "value": 2, "status": "any"}, None)
        self.assertEqual({(REAL_HOME_USER,)}, anything)
        self.assertEqual({"count": 2, "status": "any"}, context.evidence[(REAL_HOME_USER,)])

    async def test_global_scope_sums_tournaments_and_skips_other_workspaces(self) -> None:
        self._tournaments()
        self.db.foreign_tournament(OTHER_WORKSPACE_TOURNAMENT_ID)
        self.db.log_record(REAL_TOURNAMENT_ID, REAL_HOME_USER)
        self.db.log_record(LATER_TOURNAMENT_ID, REAL_HOME_USER)
        self.db.log_record(OTHER_WORKSPACE_TOURNAMENT_ID, REAL_HOME_USER)
        # No uploader to credit.
        self.db.log_record(REAL_TOURNAMENT_ID, None)
        self.db.session.commit()

        qualified, context = await self.run_node("log_upload_count", {"op": "==", "value": 2}, None)
        self.assertEqual({(REAL_HOME_USER,)}, qualified)
        self.assertEqual(2, context.evidence[(REAL_HOME_USER,)]["count"])

    async def test_tournament_scope_returns_pairs_narrowed_by_context(self) -> None:
        self._tournaments()
        self.db.log_record(REAL_TOURNAMENT_ID, REAL_HOME_USER)
        self.db.log_record(LATER_TOURNAMENT_ID, REAL_HOME_USER)
        self.db.log_record(LATER_TOURNAMENT_ID, REAL_AWAY_USER)
        self.db.session.commit()

        narrowed, _ = await self.run_node(
            "log_upload_count", {"op": ">=", "value": 1, "scope": "tournament"}, LATER_TOURNAMENT_ID
        )
        self.assertEqual(
            {(REAL_HOME_USER, LATER_TOURNAMENT_ID), (REAL_AWAY_USER, LATER_TOURNAMENT_ID)},
            narrowed,
        )

        every_tournament, _ = await self.run_node(
            "log_upload_count", {"op": ">=", "value": 1, "scope": "tournament"}, None
        )
        self.assertEqual(
            {
                (REAL_HOME_USER, REAL_TOURNAMENT_ID),
                (REAL_HOME_USER, LATER_TOURNAMENT_ID),
                (REAL_AWAY_USER, LATER_TOURNAMENT_ID),
            },
            every_tournament,
        )
