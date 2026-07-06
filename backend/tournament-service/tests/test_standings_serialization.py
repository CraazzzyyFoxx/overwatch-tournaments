from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest import IsolatedAsyncioTestCase, TestCase

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import make_transient_to_detached

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"
os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("RABBITMQ_URL", "amqp://guest:guest@localhost:5672")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

from src import models  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.standings import flows, service  # noqa: E402


def _standing() -> models.Standing:
    return models.Standing(
        id=1,
        created_at=datetime.now(UTC),
        updated_at=None,
        tournament_id=64,
        group_id=None,
        team_id=2019,
        stage_id=10,
        stage_item_id=20,
        position=1,
        overall_position=1,
        matches=0,
        win=0,
        draw=0,
        lose=0,
        points=0.0,
        buchholz=None,
        tb=None,
        score_differential=None,
    )


def _round_robin_stage() -> models.Stage:
    return models.Stage(
        id=10,
        created_at=datetime.now(UTC),
        updated_at=None,
        tournament_id=64,
        name="Group A",
        description=None,
        stage_type=enums.StageType.ROUND_ROBIN,
        max_rounds=5,
        order=0,
        is_active=True,
        is_completed=False,
        settings_json=None,
    )


def _encounter(
    *,
    id: int,
    home_team_id: int,
    away_team_id: int,
    stage_id: int,
    stage_item_id: int | None,
    round: int,
) -> models.Encounter:
    return models.Encounter(
        id=id,
        created_at=datetime.now(UTC),
        updated_at=None,
        name=f"Match {id}",
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=2,
        away_score=1,
        round=round,
        best_of=3,
        tournament_id=64,
        tournament_group_id=None,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
        closeness=None,
        has_logs=False,
        status=enums.EncounterStatus.COMPLETED,
        result_status=enums.EncounterResultStatus.NONE,
        submitted_by_id=None,
        confirmed_by_id=None,
    )


class StandingSerializationTests(IsolatedAsyncioTestCase):
    async def test_to_pydantic_does_not_lazy_load_unloaded_relationships(self) -> None:
        standing = _standing()
        make_transient_to_detached(standing)

        read = await flows.to_pydantic(cast(AsyncSession, object()), standing, [])

        self.assertIsNone(read.team)
        self.assertIsNone(read.stage)
        self.assertIsNone(read.stage_item)
        self.assertEqual(
            {
                "stage_type": None,
                "stage_name": None,
                "stage_item_name": None,
            },
            read.ranking_context,
        )
        self.assertIsNone(read.source_rule_profile)

    async def test_to_pydantic_uses_preloaded_lightweight_match_history(self) -> None:
        standing = _standing()
        history = {
            standing.team_id: [
                _encounter(
                    id=10,
                    home_team_id=standing.team_id,
                    away_team_id=2020,
                    stage_id=standing.stage_id,
                    stage_item_id=standing.stage_item_id,
                    round=1,
                ),
                _encounter(
                    id=11,
                    home_team_id=standing.team_id,
                    away_team_id=2021,
                    stage_id=999,
                    stage_item_id=standing.stage_item_id,
                    round=1,
                ),
            ]
        }

        read = await flows.to_pydantic(
            cast(AsyncSession, object()),
            standing,
            ["matches_history"],
            histories_by_team=history,
        )

        self.assertEqual([10], [encounter.id for encounter in read.matches_history])
        self.assertFalse(hasattr(read.matches_history[0], "matches"))

    async def test_to_pydantic_exposes_persisted_score_differential(self) -> None:
        standing = _standing()
        standing.score_differential = 7
        make_transient_to_detached(standing)

        read = await flows.to_pydantic(cast(AsyncSession, object()), standing, [])

        # The persisted differential is surfaced verbatim — not the old
        # ``win*2 - lose`` approximation (which would be 0 here).
        self.assertEqual(7, read.score_differential)
        assert read.tb_metrics is not None
        self.assertEqual(7, read.tb_metrics["score_differential"])

    async def test_to_pydantic_exposes_effective_tiebreak_order(self) -> None:
        standing = _standing()
        standing.stage = _round_robin_stage()

        read = await flows.to_pydantic(cast(AsyncSession, object()), standing, [])

        self.assertEqual("challonge_round_robin", read.source_rule_profile)
        self.assertEqual(
            ["points", "head_to_head", "median_buchholz", "match_wins", "score_differential"],
            read.tiebreak_order,
        )


class StandingLoadOptionTests(TestCase):
    def test_load_options_include_serializer_relationship_dependencies(self) -> None:
        paths = "\n".join(str(getattr(option, "path", "")) for option in service.standing_entities([]))

        self.assertIn("Standing.stage", paths)
        self.assertIn("Standing.stage_item", paths)

    def test_load_options_include_nested_team_relationship_dependencies(self) -> None:
        paths = "\n".join(
            str(getattr(option, "path", "")) for option in service.standing_entities(["team.placement", "team.group"])
        )

        self.assertIn("Standing.team", paths)
        self.assertIn("Team.standings", paths)
        self.assertIn("Standing.group", paths)

    def test_stage_load_options_stay_summary_only(self) -> None:
        paths = "\n".join(str(getattr(option, "path", "")) for option in service.standing_entities(["stage"]))

        self.assertIn("Standing.stage", paths)
        self.assertNotIn("Stage.items", paths)
        self.assertNotIn("StageItem.inputs", paths)


class MatchHistorySortingTests(TestCase):
    def test_sorts_swiss_matches_naturally(self) -> None:
        from shared.services.tournament_utils import sort_bracket_matches

        matches = [
            _encounter(id=1, home_team_id=1, away_team_id=2, stage_id=1, stage_item_id=1, round=3),
            _encounter(id=2, home_team_id=1, away_team_id=3, stage_id=1, stage_item_id=1, round=1),
            _encounter(id=3, home_team_id=1, away_team_id=4, stage_id=1, stage_item_id=1, round=2),
        ]
        sorted_matches = sort_bracket_matches(matches)
        self.assertEqual([2, 3, 1], [m.id for m in sorted_matches])

    def test_sorts_double_elimination_chronologically(self) -> None:
        from shared.services.tournament_utils import sort_bracket_matches

        # UB R1 (1), LB R1 (-1), UB R2 (2), LB R2 (-2), UB Final (3), LB Final (-4), Grand Final (4), GF Reset (5)
        matches = [
            _encounter(id=4, home_team_id=1, away_team_id=2, stage_id=1, stage_item_id=1, round=4),  # Grand Final
            _encounter(id=2, home_team_id=1, away_team_id=3, stage_id=1, stage_item_id=1, round=-2),  # LB R2
            _encounter(id=5, home_team_id=1, away_team_id=4, stage_id=1, stage_item_id=1, round=5),  # Grand Final Reset
            _encounter(id=1, home_team_id=1, away_team_id=5, stage_id=1, stage_item_id=1, round=2),  # UB R2
            _encounter(id=3, home_team_id=1, away_team_id=6, stage_id=1, stage_item_id=1, round=-4),  # LB Final (-4)
        ]
        sorted_matches = sort_bracket_matches(matches)
        self.assertEqual([1, 2, 3, 4, 5], [m.id for m in sorted_matches])
