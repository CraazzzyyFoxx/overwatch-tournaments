"""Node math for ``captain_report_activity`` and ``log_upload_count``.

Uses the SQLite fixture from ``test_scrim_achievement_isolation``.
"""

from __future__ import annotations

import hashlib
import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
STATS_SERVICE_ROOT = REPO_BACKEND_ROOT / "stats-service"

for candidate in (str(REPO_BACKEND_ROOT), str(STATS_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
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
importlib.import_module("shared.disciplines.overwatch.achievements.conditions.participation")  # noqa: E402

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
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def team_report(self, encounter_id: int, team_id: int, reporter_user_id: int | None) -> int:
        """A participation's report of the whole series."""
        report_id = self._id()
        self.insert(
            models.EncounterTeamReport.__table__,
            id=report_id,
            encounter_id=encounter_id,
            encounter_team_id=self.seat(encounter_id, team_id),
            reporter_user_id=reporter_user_id,
            basis_version=0,
            custom_fields_json={},
        )
        return report_id

    def game(self, encounter_id: int, position: int, *, map_id: int = 1) -> int:
        """One series position. A claim hangs off THIS, not off the encounter."""
        row_id = self._id()
        self.insert(
            models.EncounterGame.__table__,
            id=row_id,
            encounter_id=encounter_id,
            position=position,
            map_id=map_id,
            state="awaiting_result",
            result_version=0,
        )
        return row_id

    def game_claim(self, game_id: int, encounter_id: int, team_id: int, reporter_user_id: int | None) -> int:
        row_id = self._id()
        self.insert(
            models.EncounterGameClaim.__table__,
            id=row_id,
            encounter_id=encounter_id,
            game_id=game_id,
            claimant_team_id=self.seat(encounter_id, team_id),
            reporter_user_id=reporter_user_id,
            basis_version=0,
        )
        return row_id

    def game_team(self, game_id: int, encounter_id: int, team_id: int, *, replay_code: str | None = None) -> None:
        """One participation's line in a game; the replay code is written on it."""
        self.insert(
            models.EncounterGameTeam.__table__,
            game_id=game_id,
            encounter_id=encounter_id,
            encounter_team_id=self.seat(encounter_id, team_id),
            column_values={},
            replay_code=replay_code,
        )

    def readiness(self, encounter_id: int, team_id: int, ready_user_id: int | None) -> int:
        row_id = self._id()
        self.insert(
            models.EncounterReadiness.__table__,
            id=row_id,
            encounter_id=encounter_id,
            encounter_team_id=self.seat(encounter_id, team_id),
            ready_user_id=ready_user_id,
        )
        return row_id

    def log_record(
        self,
        tournament_id: int,
        uploader_id: int | None,
        *,
        status: object = models.IngestJobStatus.DONE,
        filename: str = "log.txt",
    ) -> int:
        row_id = self._id()
        self.insert(
            models.IngestJob.__table__,
            id=row_id,
            workspace_id=self.session.scalar(
                sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id)
            ),
            discipline="overwatch",
            hint_tournament_id=tournament_id,
            filename=filename,
            raw_ref=f"logs/{tournament_id}/{filename}",
            content_hash=hashlib.sha256(b"00:00:01.000,fixture log upload\n").hexdigest(),
            status=status,
            source_kind="upload",
            external_id=f"fixture-upload-{row_id}",
            uploader_user_id=uploader_id,
            attempts=0,
        )
        return row_id


class _ParticipationCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _ParticipationFixture()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await _scrim.overwatch_grid(self.db.shim)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            discipline="overwatch",
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
        report = self.db.team_report(first, home, REAL_HOME_USER)
        self.db.team_report(second, home, REAL_HOME_USER)
        # The other captain's own report for the same encounter is theirs, not ours.
        self.db.team_report(first, away, REAL_AWAY_USER)
        self.db.session.commit()
        # A captain re-submitting upserts the SAME row (unique on encounter+participation):
        # the edit must not inflate the count to three.
        self.db.session.execute(
            sa.update(models.EncounterTeamReport.__table__)
            .where(models.EncounterTeamReport.__table__.c.id == report)
            .values(games_played=3)
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
        self.db.team_report(first, home, REAL_HOME_USER)
        # Sheet-imported / account-deleted report: no reporter to credit.
        self.db.team_report(first, away, None)
        self.db.foreign_tournament(OTHER_WORKSPACE_TOURNAMENT_ID)
        foreign_team = self.db.team(OTHER_WORKSPACE_TOURNAMENT_ID, "foreign", captain_id=REAL_HOME_USER)
        foreign_encounter = self.db.encounter(OTHER_WORKSPACE_TOURNAMENT_ID, foreign_team, foreign_team)
        self.db.team_report(foreign_encounter, foreign_team, REAL_HOME_USER)
        self.db.session.commit()

        qualified, _ = await self.run_node(
            "captain_report_activity",
            {"metric": "series_reported", "op": ">=", "value": 1},
            None,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, qualified)

    async def test_map_codes_are_credited_through_the_filers_own_claim(self) -> None:
        home, away, first, _second = self._two_encounters()
        game_one = self.db.game(first, 1, map_id=1)
        game_two = self.db.game(first, 2, map_id=2)
        game_three = self.db.game(first, 3, map_id=3)
        # The code sits on the claimant's own line of the game.
        for game, code in ((game_one, "AAAAA"), (game_two, "BBBBB")):
            self.db.game_claim(game, first, home, REAL_HOME_USER)
            self.db.game_team(game, first, home, replay_code=code)
        self.db.game_claim(game_one, first, away, REAL_AWAY_USER)
        self.db.game_team(game_one, first, away, replay_code="CCCCC")
        # A claim whose own line has no code credits nothing.
        self.db.game_claim(game_three, first, home, REAL_HOME_USER)
        self.db.game_team(game_three, first, home)
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
        # Two positions of the SAME encounter, and the opposing captain's claim
        # for one of them: a claim belongs to a game, and names the encounter
        # the tournament is read from.
        game_one = self.db.game(first, 1, map_id=1)
        game_two = self.db.game(first, 2, map_id=2)
        self.db.game_claim(game_one, first, home, REAL_HOME_USER)
        self.db.game_claim(game_two, first, home, REAL_HOME_USER)
        self.db.game_claim(game_one, first, away, REAL_AWAY_USER)
        self.db.readiness(first, home, REAL_HOME_USER)
        self.db.readiness(first, away, REAL_AWAY_USER)
        self.db.readiness(second, home, REAL_HOME_USER)
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
        self.db.log_record(REAL_TOURNAMENT_ID, REAL_HOME_USER, status=models.IngestJobStatus.FAILED)
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
