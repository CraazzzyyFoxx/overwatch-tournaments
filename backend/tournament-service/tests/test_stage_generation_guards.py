"""Tests for the admin/stage.py guards around bracket generation, plus the
ahead-of-seeding bracket the same entry point builds:

* ``generate_encounters`` must never insert a second set of matches on top of
  ones that already exist -- a grouped stage skips already-generated groups
  and only fills in new ones; a non-grouped stage refuses outright.
* A bracket stage with no seeds is built from the preceding group stage's
  ``advance_count`` × groups with every slot TBD, and the teams are written
  into that same bracket once they resolve -- but only while it is provably
  untouched.
* ``deactivate_stage`` must only revert ``is_active``/``is_published`` back to
  Draft while every one of the stage's encounters is still OPEN -- the moment
  any encounter has been reported or started, it refuses instead of stranding
  real data behind a bracket that looks like a preview again.
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

enums = importlib.import_module("shared.core.enums")
errors = importlib.import_module("shared.core.errors")
stage_service = importlib.import_module("src.services.admin.stage")

HTTPException = errors.BaseAPIException


def _rows_result(rows: list[tuple]) -> SimpleNamespace:
    """Mimics ``Result.all()`` for the ``(stage_item_id, count)`` group-by."""
    return SimpleNamespace(all=lambda: rows)


def _scalar_result(value: int) -> SimpleNamespace:
    return SimpleNamespace(scalar_one=lambda: value)


def _item(item_id: int, name: str = "Group", order: int = 0, item_type=None) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, name=name, order=order, type=item_type, inputs=[])


def _scalars_result(rows: list) -> SimpleNamespace:
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _encounter(round_number: int, encounter_id: int, **overrides) -> SimpleNamespace:
    fields = {
        "id": encounter_id,
        "round": round_number,
        "home_team_id": None,
        "away_team_id": None,
        "status": enums.EncounterStatus.OPEN,
        "name": "TBD vs TBD",
    }
    return SimpleNamespace(**{**fields, **overrides})


def _queued_session(results: list) -> SimpleNamespace:
    """A session whose ``execute`` hands back ``results`` in call order."""
    queue = list(results)
    return SimpleNamespace(execute=AsyncMock(side_effect=lambda *_a, **_kw: queue.pop(0)), flush=AsyncMock())


class GenerateEncountersGuardTests(IsolatedAsyncioTestCase):
    async def test_grouped_stage_skips_items_that_already_have_matches(self) -> None:
        """Group A already has matches; Group B (newly added) does not -- only
        Group B gets generated, and Group A's existing matches are untouched."""
        item_a, item_b = _item(1, "Group A"), _item(2, "Group B")
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([(1, 10)])), flush=AsyncMock())
        stage = SimpleNamespace(id=77, tournament_id=1, stage_type=enums.StageType.SWISS, items=[item_a, item_b])
        new_encounter = SimpleNamespace(id=901)

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_collect_item_team_ids", lambda item: [10, 20]),
            patch.object(stage_service.stage_service, "_generate_stage_skeleton", AsyncMock(return_value="skeleton")),
            patch.object(stage_service.stage_service, "_load_team_names", AsyncMock(return_value={})),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[new_encounter])
            ) as create,
            patch.object(stage_service, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            result = await stage_service.stage_service.generate_encounters(session, 77, commit=False)

        self.assertEqual([new_encounter], result)
        # Only Group B (item 2, the one with zero existing matches) was generated.
        self.assertEqual(1, create.await_count)
        self.assertEqual(item_b.id, create.await_args.args[3])

    async def test_grouped_stage_rejects_when_every_group_already_has_matches(self) -> None:
        item_a, item_b = _item(1, "Group A"), _item(2, "Group B")
        stage = SimpleNamespace(id=77, stage_type=enums.StageType.SWISS, items=[item_a, item_b])
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([(1, 10), (2, 10)])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock()) as create,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 77, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        create.assert_not_awaited()

    async def test_non_grouped_stage_rejects_regeneration_over_existing_matches(self) -> None:
        item = _item(1, "Bracket")
        stage = SimpleNamespace(id=88, stage_type=enums.StageType.SINGLE_ELIMINATION, items=[item])
        # One existing encounter already recorded against this stage.
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([(1, 8)])))

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=None)),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock()) as create,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 88, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        create.assert_not_awaited()

    async def test_non_grouped_stage_still_generates_from_a_clean_slate(self) -> None:
        """Regression guard: a stage with zero existing encounters must still
        generate normally through the (now-guarded) non-grouped path."""
        item = _item(1, "Bracket")
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[item],
            split_lower_bracket=False,
            settings_json={},
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])), flush=AsyncMock())
        new_encounters = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
            patch.object(stage_service.stage_service, "_generate_stage_skeleton", AsyncMock(return_value="skeleton")),
            patch.object(stage_service.stage_service, "_load_team_names", AsyncMock(return_value={})),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=new_encounters)
            ) as create,
            patch.object(stage_service, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            result = await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        self.assertEqual(new_encounters, result)
        create.assert_awaited_once()

    async def test_avg_sr_ranking_reorders_teams_before_the_engine(self) -> None:
        item = _item(1, "Bracket")
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[item],
            split_lower_bracket=False,
            settings_json={"seed_ranking": "avg_sr"},
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])), flush=AsyncMock())
        teams = {
            1: SimpleNamespace(id=1, avg_sr=2200.0, total_sr=0),
            2: SimpleNamespace(id=2, avg_sr=1800.0, total_sr=0),
            3: SimpleNamespace(id=3, avg_sr=3100.0, total_sr=0),
            4: SimpleNamespace(id=4, avg_sr=2500.0, total_sr=0),
        }

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
            patch.object(stage_service.stage_service, "_load_rankable_teams", AsyncMock(return_value=teams)),
            patch.object(
                stage_service.stage_service, "_generate_stage_skeleton", AsyncMock(return_value="skeleton")
            ) as gen,
            patch.object(stage_service.stage_service, "_load_team_names", AsyncMock(return_value={})),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[])),
            patch.object(stage_service, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        self.assertEqual([3, 4, 1, 2], gen.await_args.args[2])

    async def test_builds_a_tbd_bracket_from_the_group_stage_advance_count(self) -> None:
        """The playoff has no seeds yet -- 2 advance from each of 4 groups, so
        the 8-team bracket is generated now with every slot left TBD."""
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, "Bracket")],
            split_lower_bracket=False,
            settings_json={},
        )
        source = SimpleNamespace(id=4, advance_count=2, items=[_item(i, order=i) for i in range(4)])
        session = _queued_session([_rows_result([])])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[])
            ) as create,
            patch.object(stage_service, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        skeleton = create.await_args.args[2]
        # 8 teams → 7 matches over 3 rounds, and not one of them names a team:
        # the seeds only exist as group placements until the groups finish.
        self.assertEqual(7, len(skeleton.pairings))
        self.assertEqual([1, 2, 3], sorted({p.round_number for p in skeleton.pairings}))
        self.assertTrue(all(p.home_team_id is None and p.away_team_id is None for p in skeleton.pairings))

    async def test_a_group_override_changes_the_projected_bracket_size(self) -> None:
        """One group advancing 3 while the other three advance the stage's 2 makes
        9 seeds, not 8 -- a 16-slot bracket with byes, one round deeper."""
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, "Bracket")],
            split_lower_bracket=False,
            settings_json={},
        )
        source = SimpleNamespace(id=4, advance_count=2, items=[_item(i, order=i) for i in range(4)])
        source.items[0].advance_count = 3
        session = _queued_session([_rows_result([])])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[])
            ) as create,
            patch.object(stage_service, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        skeleton = create.await_args.args[2]
        self.assertEqual([1, 2, 3, 4], sorted({p.round_number for p in skeleton.pairings}))

    async def test_seeds_resolved_teams_into_the_bracket_it_already_generated(self) -> None:
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, "Bracket")],
            split_lower_bracket=False,
            settings_json={},
        )
        # The TBD bracket generated earlier: two semifinals and a final.
        existing = [_encounter(1, 10), _encounter(1, 11), _encounter(2, 12)]
        session = _queued_session([_rows_result([(1, 3)]), _scalars_result(existing)])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
            patch.object(
                stage_service.stage_service,
                "_load_team_names",
                AsyncMock(return_value={1: "A", 2: "B", 3: "C", 4: "D"}),
            ),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock()) as create,
            patch.object(stage_service, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            result = await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        # Same encounters, now seeded 1v4 / 2v3 the way the generator pairs them
        # — no second bracket, so ids, schedule and links all survive.
        self.assertEqual(existing, result)
        create.assert_not_awaited()
        self.assertEqual([(1, 4), (2, 3)], [(e.home_team_id, e.away_team_id) for e in existing[:2]])
        self.assertEqual("A vs D", existing[0].name)
        self.assertEqual((None, None), (existing[2].home_team_id, existing[2].away_team_id))

    async def test_refuses_to_reseed_a_bracket_that_is_already_being_played(self) -> None:
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, "Bracket")],
            split_lower_bracket=False,
            settings_json={},
        )
        existing = [_encounter(1, 10, home_team_id=7), _encounter(1, 11), _encounter(2, 12)]
        session = _queued_session([_rows_result([(1, 3)]), _scalars_result(existing)])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock()) as create,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        create.assert_not_awaited()

    async def test_refuses_to_reseed_when_the_resolved_teams_change_the_shape(self) -> None:
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, "Bracket")],
            split_lower_bracket=False,
            settings_json={},
        )
        # A 4-team bracket was generated; 8 teams resolved. Reseeding in place
        # would leave half of them out, so it refuses and asks for a rebuild.
        existing = [_encounter(1, 10), _encounter(1, 11), _encounter(2, 12)]
        session = _queued_session([_rows_result([(1, 3)]), _scalars_result(existing)])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service, "_bracket_seeds", lambda *_: (list(range(1, 9)), [])),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock()) as create,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        create.assert_not_awaited()
        self.assertTrue(all(e.home_team_id is None for e in existing))


class DeactivateStageGuardTests(IsolatedAsyncioTestCase):
    async def test_reverts_an_untouched_stage_to_draft(self) -> None:
        stage = SimpleNamespace(id=5, tournament_id=1, is_active=True, is_published=True)
        session = SimpleNamespace(execute=AsyncMock(return_value=_scalar_result(0)), flush=AsyncMock())

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(side_effect=[stage, stage])),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()) as notify,
        ):
            result = await stage_service.stage_service.deactivate_stage(session, 5, commit=False)

        self.assertFalse(stage.is_active)
        self.assertFalse(stage.is_published)
        self.assertIs(stage, result)
        notify.assert_awaited_once()
        session.flush.assert_awaited_once()

    async def test_refuses_once_any_encounter_left_open(self) -> None:
        stage = SimpleNamespace(id=5, tournament_id=1, is_active=True, is_published=True)
        session = SimpleNamespace(execute=AsyncMock(return_value=_scalar_result(1)))

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.deactivate_stage(session, 5, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        # Refused before mutating anything.
        self.assertTrue(stage.is_active)
        self.assertTrue(stage.is_published)
