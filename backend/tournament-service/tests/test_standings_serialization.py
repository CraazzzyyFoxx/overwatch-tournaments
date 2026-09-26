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

from src import models  # noqa: E402
from src.core import enums  # noqa: E402
from src.services.standings import flows, service  # noqa: E402
from tests._stage_regulation import stage_regulation  # noqa: E402


def _standing() -> models.Standing:
    return models.Standing(
        id=1,
        created_at=datetime.now(UTC),
        updated_at=None,
        tournament_id=64,
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
        full_buchholz=None,
        tie_group=None,
        tb=None,
        score_differential=None,
        is_pinned=False,
    )


def _round_robin_stage() -> models.Stage:
    return models.Stage(
        **stage_regulation(),
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
    )


def _encounter(
    *,
    id: int,
    home_team_id: int,
    away_team_id: int,
    stage_id: int,
    stage_item_id: int | None,
    round: int,
    status: enums.EncounterStatus = enums.EncounterStatus.COMPLETED,
) -> models.Encounter:
    return models.Encounter(
        id=id,
        created_at=datetime.now(UTC),
        updated_at=None,
        name=f"Match {id}",
        format=enums.EncounterFormat.DUEL.value,
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        home_score=2,
        away_score=1,
        round=round,
        best_of=3,
        tournament_id=64,
        stage_id=stage_id,
        stage_item_id=stage_item_id,
        closeness=None,
        has_logs=False,
        status=status,
        result_status=enums.EncounterResultStatus.NONE,
    )


class _ScalarResult:
    def __init__(self, rows: list[models.Encounter]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[models.Encounter]:
        return self._rows


class _StubSession:
    """Returns a fixed encounter set, ordered as the query's ORDER BY would."""

    def __init__(self, rows: list[models.Encounter]) -> None:
        self._rows = rows

    async def execute(self, _query: object) -> _ScalarResult:
        return _ScalarResult(self._rows)


class StandingSerializationTests(IsolatedAsyncioTestCase):
    async def test_to_pydantic_does_not_lazy_load_unloaded_relationships(self) -> None:
        standing = _standing()
        make_transient_to_detached(standing)

        read = await flows.flows_service.to_pydantic(cast(AsyncSession, object()), standing, [])

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

        read = await flows.flows_service.to_pydantic(
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

        read = await flows.flows_service.to_pydantic(cast(AsyncSession, object()), standing, [])

        # The persisted differential is surfaced verbatim — not the old
        # ``win*2 - lose`` approximation (which would be 0 here).
        self.assertEqual(7, read.score_differential)
        assert read.tb_metrics is not None
        self.assertEqual(7, read.tb_metrics["score_differential"])

    async def test_to_pydantic_exposes_effective_tiebreak_order(self) -> None:
        standing = _standing()
        standing.stage = _round_robin_stage()

        read = await flows.flows_service.to_pydantic(cast(AsyncSession, object()), standing, [])

        self.assertEqual("challonge_round_robin", read.source_rule_profile)
        # The preset's own order: the legend names exactly what ranked the row.
        self.assertEqual(
            [
                "points",
                "head_to_head",
                "median_buchholz",
                "match_wins",
                "score_differential",
            ],
            read.tiebreak_order,
        )


class MatchHistoryRoundScopeTests(IsolatedAsyncioTestCase):
    """FORM must not run ahead of the W·D·L it sits next to."""

    async def test_history_drops_results_from_unfinished_rounds(self) -> None:
        rows = [
            # Group A, round 1: closed.
            _encounter(id=1, home_team_id=1, away_team_id=2, stage_id=10, stage_item_id=20, round=1),
            _encounter(id=2, home_team_id=3, away_team_id=4, stage_id=10, stage_item_id=20, round=1),
            # Group A, round 2: one team reported, the other pair has not.
            _encounter(id=3, home_team_id=1, away_team_id=3, stage_id=10, stage_item_id=20, round=2),
            _encounter(
                id=4,
                home_team_id=2,
                away_team_id=4,
                stage_id=10,
                stage_item_id=20,
                round=2,
                status=enums.EncounterStatus.PENDING,
            ),
            # Group B, round 2: closed — an open round in group A must not hide it.
            _encounter(id=5, home_team_id=5, away_team_id=6, stage_id=10, stage_item_id=21, round=2),
        ]

        history = await service.standings_service.get_completed_match_history_by_tournament(
            cast(AsyncSession, _StubSession(rows)), 64
        )

        self.assertEqual([1, 2, 5], [encounter.id for encounter in history])


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
        self.assertIn("Standing.stage_item", paths)

    def test_stage_load_options_stay_summary_only(self) -> None:
        paths = "\n".join(str(getattr(option, "path", "")) for option in service.standing_entities(["stage"]))

        self.assertIn("Standing.stage", paths)
        self.assertNotIn("Stage.items", paths)
        self.assertNotIn("StageItem.inputs", paths)


class MatchHistorySortingTests(TestCase):
    def test_sorts_swiss_matches_naturally(self) -> None:
        from shared.domain.tournament_utils import sort_bracket_matches

        matches = [
            _encounter(id=1, home_team_id=1, away_team_id=2, stage_id=1, stage_item_id=1, round=3),
            _encounter(id=2, home_team_id=1, away_team_id=3, stage_id=1, stage_item_id=1, round=1),
            _encounter(id=3, home_team_id=1, away_team_id=4, stage_id=1, stage_item_id=1, round=2),
        ]
        sorted_matches = sort_bracket_matches(matches)
        self.assertEqual([2, 3, 1], [m.id for m in sorted_matches])

    def test_sorts_double_elimination_chronologically(self) -> None:
        from shared.domain.tournament_utils import sort_bracket_matches

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
