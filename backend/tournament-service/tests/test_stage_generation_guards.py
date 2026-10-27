"""Tests for the admin/stage guards around bracket generation, plus the
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
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


enums = importlib.import_module("shared.core.enums")
errors = importlib.import_module("shared.core.errors")
stage_service = importlib.import_module("src.services.admin.stage")
stage_base = importlib.import_module("src.services.admin.stage.base")
stage_generation = importlib.import_module("src.services.admin.stage.generation")

from tests._stage_regulation import stage_regulation  # noqa: E402

HTTPException = errors.BaseAPIException


def _rows_result(rows: list[tuple]) -> SimpleNamespace:
    """Mimics ``Result.all()`` for the ``(stage_item_id, count)`` group-by."""
    return SimpleNamespace(all=lambda: rows)


def _scalar_result(value: int) -> SimpleNamespace:
    return SimpleNamespace(scalar_one=lambda: value)


def _item(item_id: int, name: str = "Group", order: int = 0, item_type=None) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, name=name, order=order, type=item_type, inputs=[])


def _tuples_result(rows: list[tuple]) -> SimpleNamespace:
    """``_fill_bracket_seeds`` reads ``(Encounter, round)`` pairs: the round
    lives on ``tournament.bracket_encounter`` now (D22)."""
    return SimpleNamespace(tuples=lambda: SimpleNamespace(all=lambda: rows))


def _encounter(round_number: int, encounter_id: int, **overrides) -> tuple[SimpleNamespace, int]:
    """One row of that pair. ``slot_count`` is what makes it a duel; there is no
    home or away column to set."""
    fields = {
        "id": encounter_id,
        "slot_count": 2,
        "status": enums.EncounterStatus.OPEN,
        "name": "TBD vs TBD",
    }
    return SimpleNamespace(**{**fields, **overrides}), round_number


def _queued_session(results: list, *, seated: int = 0) -> SimpleNamespace:
    """A session whose ``execute`` hands back ``results`` in call order; a row
    lock (``SELECT … FOR UPDATE``) returns nothing and consumes none of them.
    ``seated`` is what the participation count behind the preview check answers."""
    queue = list(results)

    def execute(statement=None, *_a, **_kw):
        if "FOR UPDATE" in str(statement):
            return _rows_result([])
        return queue.pop(0)

    return SimpleNamespace(
        execute=AsyncMock(side_effect=execute),
        scalar=AsyncMock(return_value=seated),
        flush=AsyncMock(),
    )


class GenerateEncountersGuardTests(IsolatedAsyncioTestCase):
    async def test_grouped_stage_skips_items_that_already_have_matches(self) -> None:
        """Group A already has matches; Group B (newly added) does not -- only
        Group B gets generated, and Group A's existing matches are untouched."""
        item_a, item_b = _item(1, "Group A"), _item(2, "Group B")
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([(1, 10)])), flush=AsyncMock())
        stage = SimpleNamespace(
            id=77,
            tournament_id=1,
            stage_type=enums.StageType.SWISS,
            items=[item_a, item_b],
            is_published=False,
            **stage_regulation(),
        )
        new_encounter = SimpleNamespace(id=901)

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_generation, "_collect_item_team_ids", lambda item: [10, 20]),
            patch.object(stage_service.stage_service, "_generate_stage_skeleton", AsyncMock(return_value="skeleton")),
            patch.object(stage_service.stage_service, "_load_team_names", AsyncMock(return_value={})),
            patch.object(stage_service.stage_service, "_team_lineups", AsyncMock(return_value={})),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[new_encounter])
            ) as create,
            patch.object(stage_base, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            result = await stage_service.stage_service.generate_encounters(session, 77, commit=False)

        self.assertEqual([new_encounter], result)
        # Only Group B (item 2, the one with zero existing matches) was generated.
        self.assertEqual(1, create.await_count)
        self.assertEqual(item_b.id, create.await_args.args[3])

    async def test_grouped_stage_rejects_when_every_group_already_has_matches(self) -> None:
        item_a, item_b = _item(1, "Group A"), _item(2, "Group B")
        stage = SimpleNamespace(id=77, stage_type=enums.StageType.SWISS, items=[item_a, item_b], **stage_regulation())
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
        stage = SimpleNamespace(
            id=88, stage_type=enums.StageType.SINGLE_ELIMINATION, items=[item], **stage_regulation()
        )
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
            is_published=False,
            **stage_regulation(),
        )
        session = SimpleNamespace(execute=AsyncMock(return_value=_rows_result([])), flush=AsyncMock())
        new_encounters = [SimpleNamespace(id=1), SimpleNamespace(id=2)]

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_generation, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
            patch.object(stage_service.stage_service, "_generate_stage_skeleton", AsyncMock(return_value="skeleton")),
            patch.object(stage_service.stage_service, "_load_team_names", AsyncMock(return_value={})),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=new_encounters)
            ) as create,
            patch.object(stage_base, "enqueue_tournament_recalculation", AsyncMock()),
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
            is_published=False,
            **stage_regulation(seed_ranking="avg_sr"),
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
            patch.object(stage_generation, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
            patch.object(stage_service.stage_service, "_load_rankable_teams", AsyncMock(return_value=teams)),
            patch.object(
                stage_service.stage_service, "_generate_stage_skeleton", AsyncMock(return_value="skeleton")
            ) as gen,
            patch.object(stage_service.stage_service, "_load_team_names", AsyncMock(return_value={})),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[])),
            patch.object(stage_base, "enqueue_tournament_recalculation", AsyncMock()),
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
            is_published=False,
            **stage_regulation(),
        )
        source = SimpleNamespace(
            id=4, advance_count=2, advance_upper_count=None, items=[_item(i, order=i) for i in range(4)]
        )
        session = _queued_session([_rows_result([])])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[])
            ) as create,
            patch.object(stage_base, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        skeleton = create.await_args.args[2]
        # 8 teams → 7 matches over 3 rounds, and not one of them names a team:
        # the seeds only exist as group placements until the groups finish.
        self.assertEqual(7, len(skeleton.pairings))
        self.assertEqual([1, 2, 3], sorted({p.round_number for p in skeleton.pairings}))
        # Every seat is TBD: a pairing is ``team_ids[i]`` per slot now (D55).
        self.assertTrue(all(all(team_id is None for team_id in p.team_ids) for p in skeleton.pairings))

    async def test_a_group_override_changes_the_projected_bracket_size(self) -> None:
        """One group advancing 3 while the other three advance the stage's 2 makes
        9 seeds, not 8 -- a 16-slot bracket with byes, one round deeper."""
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, "Bracket")],
            is_published=False,
            **stage_regulation(),
        )
        source = SimpleNamespace(
            id=4, advance_count=2, advance_upper_count=None, items=[_item(i, order=i) for i in range(4)]
        )
        source.items[0].advance_count = 3
        session = _queued_session([_rows_result([])])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_service.stage_service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(
                stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock(return_value=[])
            ) as create,
            patch.object(stage_base, "enqueue_tournament_recalculation", AsyncMock()),
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
            is_published=False,
            **stage_regulation(),
        )
        # The TBD bracket generated earlier: two semifinals and a final.
        existing = [_encounter(1, 10), _encounter(1, 11), _encounter(2, 12)]
        session = _queued_session([_rows_result([(1, 3)]), _tuples_result(existing)])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_generation, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
            patch.object(
                stage_service.stage_service,
                "_load_team_names",
                AsyncMock(return_value={1: "A", 2: "B", 3: "C", 4: "D"}),
            ),
            patch.object(stage_service.stage_service, "_team_lineups", AsyncMock(return_value={})),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock()) as create,
            patch.object(stage_generation, "place_team", AsyncMock()) as seat,
            patch.object(stage_base, "enqueue_tournament_recalculation", AsyncMock()),
            patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()),
        ):
            result = await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        # Same encounters, now seeded 1v4 / 2v3 the way the generator pairs them
        # — no second bracket, so ids, schedule and links all survive.
        self.assertEqual([encounter for encounter, _round in existing], result)
        create.assert_not_awaited()
        # Seeded 1v4 / 2v3 the way the generator pairs them, through the
        # participation writer -- slot 1 then slot 2 of each semifinal.
        self.assertEqual(
            [(10, 1, 1), (10, 2, 4), (11, 1, 2), (11, 2, 3)],
            [(call.args[1].id, call.kwargs["slot"], call.kwargs["team_id"]) for call in seat.await_args_list],
        )
        self.assertEqual("A vs D", existing[0][0].name)
        self.assertEqual("TBD vs TBD", existing[2][0].name)

    async def test_refuses_to_reseed_a_bracket_that_is_already_being_played(self) -> None:
        stage = SimpleNamespace(
            id=99,
            tournament_id=1,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, "Bracket")],
            **stage_regulation(),
        )
        existing = [_encounter(1, 10), _encounter(1, 11), _encounter(2, 12)]
        # One participation anywhere in the stage -- live or retired -- means this
        # bracket was played, not previewed.
        session = _queued_session([_rows_result([(1, 3)]), _tuples_result(existing)], seated=1)

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_generation, "_bracket_seeds", lambda *_: ([1, 2, 3, 4], [])),
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
            **stage_regulation(),
        )
        # A 4-team bracket was generated; 8 teams resolved. Reseeding in place
        # would leave half of them out, so it refuses and asks for a rebuild.
        existing = [_encounter(1, 10), _encounter(1, 11), _encounter(2, 12)]
        session = _queued_session([_rows_result([(1, 3)]), _tuples_result(existing)])

        with (
            patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(stage_generation, "_bracket_seeds", lambda *_: (list(range(1, 9)), [])),
            patch.object(stage_service.stage_service, "_create_encounters_from_skeleton", AsyncMock()) as create,
        ):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.generate_encounters(session, 99, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        create.assert_not_awaited()


class ActivateStageParallelPhaseTests(IsolatedAsyncioTestCase):
    """Activating a stage moves the tournament to that stage's PHASE.

    Stages sharing an ``order`` (the Low and High divisions of one wave) run at
    the same time, so activation may only clear ``is_active`` on OTHER phases —
    clearing it per-stage made the second division switch the first one off.
    """

    async def test_activation_leaves_the_phase_siblings_active(self) -> None:
        stage = SimpleNamespace(id=5, tournament_id=1, order=2, items=[], is_active=False, is_published=False)
        statements: list = []

        def _record(statement, *_a, **_kw):  # noqa: ANN001, ANN002, ANN003, ANN202
            statements.append(statement)
            # The stage has no encounters to notify about.
            return SimpleNamespace(scalars=lambda: iter(()))

        session = SimpleNamespace(execute=AsyncMock(side_effect=_record), flush=AsyncMock())

        with patch.object(stage_service.stage_service, "_publish_structure_changed", AsyncMock()):
            await stage_service.stage_service.activate_stage(session, 5, commit=False, stage=stage)

        self.assertTrue(stage.is_active)
        self.assertTrue(stage.is_published)
        sql = str(statements[0].compile(compile_kwargs={"literal_binds": True}))
        self.assertIn("!= 2", sql)
        self.assertNotIn("!= 5", sql)


class DeactivateStageGuardTests(IsolatedAsyncioTestCase):
    async def test_reverts_an_untouched_stage_to_draft(self) -> None:
        stage = SimpleNamespace(id=5, tournament_id=1, is_active=True, is_published=True)
        # ``deactivate_stage`` counts non-OPEN encounters with one scalar over
        # ``tournament.bracket_encounter``.
        session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=0), flush=AsyncMock())

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
        session = SimpleNamespace(execute=AsyncMock(), scalar=AsyncMock(return_value=1))

        with patch.object(stage_service.stage_service, "get_stage", AsyncMock(return_value=stage)):
            with self.assertRaises(HTTPException) as ctx:
                await stage_service.stage_service.deactivate_stage(session, 5, commit=False)

        self.assertEqual(409, ctx.exception.status_code)
        # Refused before mutating anything.
        self.assertTrue(stage.is_active)
        self.assertTrue(stage.is_published)
