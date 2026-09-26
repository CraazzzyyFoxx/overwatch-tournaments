"""Per-round best-of config reading, resolution, and backfill."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


best_of = importlib.import_module("src.domain.admin.best_of")
stage_service = importlib.import_module("src.services.admin.stage")
enums = importlib.import_module("shared.core.enums")

from tests._stage_regulation import stage_regulation  # noqa: E402


def _stage(**overrides) -> SimpleNamespace:
    return SimpleNamespace(**stage_regulation(**overrides))


class BestOfConfigTests(TestCase):
    def test_reads_default_final_and_the_round_rows(self) -> None:
        # Lower-bracket rounds are negative, and the frontend mirror
        # (frontend/src/lib/tournament/best-of.ts) keeps them to match.
        cfg = best_of.best_of_config(_stage(best_of_default=3, best_of_final=7, by_round={-1: 5, 2: 2}))

        self.assertEqual(cfg.default, 3)
        self.assertEqual(cfg.by_round, {-1: 5, 2: 2})
        self.assertEqual(cfg.final, 7)

    def test_a_fresh_stage_is_default_only(self) -> None:
        cfg = best_of.best_of_config(_stage())

        self.assertEqual(cfg.default, 3)
        self.assertEqual(cfg.by_round, {})
        self.assertIsNone(cfg.final)


class ResolveBestOfTests(TestCase):
    def test_default_when_no_override(self) -> None:
        cfg = best_of.BestOfConfig(default=3, by_round={}, final=None)
        self.assertEqual(best_of.resolve_best_of(cfg, 2, is_final=False), 3)

    def test_by_round_override(self) -> None:
        cfg = best_of.BestOfConfig(default=3, by_round={1: 2}, final=None)
        self.assertEqual(best_of.resolve_best_of(cfg, 1, is_final=False), 2)
        self.assertEqual(best_of.resolve_best_of(cfg, 2, is_final=False), 3)

    def test_final_takes_precedence_when_is_final(self) -> None:
        cfg = best_of.BestOfConfig(default=3, by_round={2: 3}, final=5)
        # round 2 is the final -> final wins over the by_round entry
        self.assertEqual(best_of.resolve_best_of(cfg, 2, is_final=True), 5)
        # same round, not flagged final -> by_round applies
        self.assertEqual(best_of.resolve_best_of(cfg, 2, is_final=False), 3)

    def test_final_ignored_when_unset(self) -> None:
        cfg = best_of.BestOfConfig(default=3, by_round={}, final=None)
        self.assertEqual(best_of.resolve_best_of(cfg, 9, is_final=True), 3)


class _FakeScalarResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalarResult:
        return self

    def all(self) -> list:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list) -> None:
        self._rows = rows
        self.committed = False

    async def execute(self, _query) -> _FakeScalarResult:
        return _FakeScalarResult(self._rows)

    async def commit(self) -> None:
        self.committed = True


class ApplyBestOfToExistingTests(TestCase):
    def _run_backfill(self, stage, encounters):
        session = _FakeSession(encounters)

        async def _fake_get_stage(_session, _stage_id):
            return stage

        published: list[tuple] = []

        async def _fake_publish(_session, tournament_id):
            published.append(tournament_id)

        orig_get_stage = stage_service.stage_service.get_stage
        orig_publish = stage_service.stage_service._publish_structure_changed
        stage_service.stage_service.get_stage = _fake_get_stage
        stage_service.stage_service._publish_structure_changed = _fake_publish
        try:
            changed = asyncio.run(stage_service.stage_service.apply_best_of_to_existing(session, stage.id))
        finally:
            stage_service.stage_service.get_stage = orig_get_stage
            stage_service.stage_service._publish_structure_changed = orig_publish
        return changed, session, published

    def test_rewrites_per_round_and_final_for_elimination(self) -> None:
        stage = _stage(
            id=10,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            best_of_default=3,
            best_of_final=5,
            by_round={1: 1},
        )
        duel = enums.EncounterFormat.DUEL
        encounters = [
            SimpleNamespace(round=1, best_of=3, format=duel),  # by_round -> 1
            SimpleNamespace(round=2, best_of=3, format=duel),  # default (not max round)
            SimpleNamespace(round=3, best_of=3, format=duel),  # max round + elimination -> final 5
        ]
        changed, session, published = self._run_backfill(stage, encounters)

        self.assertEqual([e.best_of for e in encounters], [1, 3, 5])
        self.assertEqual(changed, 2)  # rounds 1 and 3 changed; round 2 unchanged
        self.assertTrue(session.committed)
        self.assertEqual(published, [1])

    def test_no_final_override_for_group_stage(self) -> None:
        stage = _stage(
            id=11,
            tournament_id=2,
            stage_type=enums.StageType.ROUND_ROBIN,
            best_of_default=2,
            best_of_final=5,
        )
        encounters = [
            SimpleNamespace(round=1, best_of=3, format=enums.EncounterFormat.DUEL),
            # Highest round, but not elimination.
            SimpleNamespace(round=2, best_of=3, format=enums.EncounterFormat.DUEL),
        ]
        changed, session, _ = self._run_backfill(stage, encounters)

        self.assertEqual([e.best_of for e in encounters], [2, 2])
        self.assertEqual(changed, 2)

    def test_no_changes_leaves_commit_but_no_publish(self) -> None:
        # Nothing configured -> everything resolves to the default 3.
        stage = _stage(id=12, tournament_id=3, stage_type=enums.StageType.SINGLE_ELIMINATION)
        encounters = [SimpleNamespace(round=1, best_of=3, format=enums.EncounterFormat.DUEL)]
        changed, session, published = self._run_backfill(stage, encounters)

        self.assertEqual(changed, 0)
        self.assertTrue(session.committed)
        self.assertEqual(published, [])
