"""Phase F2: tests for wire-from-groups and activate-and-generate.

Verify the two-stage tournament workflow (groups → playoffs).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "parser-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("S3_ACCESS_KEY", "test")
os.environ.setdefault("S3_SECRET_KEY", "test")
os.environ.setdefault("S3_ENDPOINT_URL", "http://localhost")
os.environ.setdefault("S3_BUCKET_NAME", "test")

stage_service = importlib.import_module("src.services.admin.stage")
admin_schemas_module = importlib.import_module("src.schemas.admin.stage")
enums = importlib.import_module("shared.core.enums")

stage_service._publish_tournament_changed = AsyncMock()



def _group_stage(
    *, stage_id: int, tournament_id: int, num_groups: int
) -> SimpleNamespace:
    """Helper: build a round-robin source stage with ``num_groups`` items."""
    items = [
        SimpleNamespace(
            id=100 + g,
            name=chr(65 + g),  # A, B, C, ...
            order=g,
            inputs=[],
        )
        for g in range(num_groups)
    ]
    return SimpleNamespace(
        id=stage_id,
        tournament_id=tournament_id,
        stage_type=enums.StageType.ROUND_ROBIN,
        items=items,
    )


def _playoff_stage(
    *, stage_id: int, tournament_id: int, stage_item_id: int = 200
) -> SimpleNamespace:
    return SimpleNamespace(
        id=stage_id,
        tournament_id=tournament_id,
        stage_type=enums.StageType.SINGLE_ELIMINATION,
        items=[
            SimpleNamespace(
                id=stage_item_id,
                name="Playoffs",
                order=0,
                inputs=[],
            )
        ],
    )


class WireFromGroupsTests(IsolatedAsyncioTestCase):
    async def test_cross_seeding_two_groups_top_2(self) -> None:
        tournament_id = 99
        source = _group_stage(stage_id=1, tournament_id=tournament_id, num_groups=2)
        target = _playoff_stage(stage_id=2, tournament_id=tournament_id)

        added_inputs: list = []
        session = SimpleNamespace(
            add=Mock(side_effect=lambda obj: added_inputs.append(obj)),
            commit=AsyncMock(),
        )

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source, target]),
        ):
            await stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=2,
            )

        # 2 groups × top 2 = 4 slots
        self.assertEqual(4, len(added_inputs))

        # All TENTATIVE with valid source refs
        for inp in added_inputs:
            self.assertEqual(
                enums.StageItemInputType.TENTATIVE, inp.input_type
            )
            self.assertIsNone(inp.team_id)
            self.assertIsNotNone(inp.source_stage_item_id)
            self.assertIsNotNone(inp.source_position)

        # Cross seeding: column 0 = (A, 1), (B, 1); column 1 = (B, 2), (A, 2)
        # Expected (slot, source_item.name, position):
        # 1 → A, 1
        # 2 → B, 1
        # 3 → B, 2
        # 4 → A, 2
        expected = [(1, 100, 1), (2, 101, 1), (3, 101, 2), (4, 100, 2)]
        actual = [
            (inp.slot, inp.source_stage_item_id, inp.source_position)
            for inp in added_inputs
        ]
        self.assertEqual(expected, actual)

    async def test_snake_seeding_two_groups_top_2(self) -> None:
        tournament_id = 99
        source = _group_stage(stage_id=1, tournament_id=tournament_id, num_groups=2)
        target = _playoff_stage(stage_id=2, tournament_id=tournament_id)

        added_inputs: list = []
        session = SimpleNamespace(
            add=Mock(side_effect=lambda obj: added_inputs.append(obj)),
            commit=AsyncMock(),
        )

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source, target]),
        ):
            await stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=2,
                mode="snake",
            )

        # Snake: A1, B1, A2, B2
        expected = [(1, 100, 1), (2, 101, 1), (3, 100, 2), (4, 101, 2)]
        actual = [
            (inp.slot, inp.source_stage_item_id, inp.source_position)
            for inp in added_inputs
        ]
        self.assertEqual(expected, actual)

    async def test_preserves_final_inputs(self) -> None:
        tournament_id = 99
        source = _group_stage(stage_id=1, tournament_id=tournament_id, num_groups=2)
        target = _playoff_stage(stage_id=2, tournament_id=tournament_id)

        # Slot 1 already has a manually-assigned team — must not be overwritten.
        pre_existing_final = SimpleNamespace(
            slot=1,
            input_type=enums.StageItemInputType.FINAL,
            team_id=777,
            source_stage_item_id=None,
            source_position=None,
        )
        target.items[0].inputs.append(pre_existing_final)

        added_inputs: list = []
        session = SimpleNamespace(
            add=Mock(side_effect=lambda obj: added_inputs.append(obj)),
            commit=AsyncMock(),
        )

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source, target]),
        ):
            await stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=2,
            )

        # Only 3 new TENTATIVE inputs (slot 1 is preserved as FINAL)
        self.assertEqual(3, len(added_inputs))
        self.assertEqual({2, 3, 4}, {inp.slot for inp in added_inputs})

        # Pre-existing FINAL is untouched
        self.assertEqual(enums.StageItemInputType.FINAL, pre_existing_final.input_type)
        self.assertEqual(777, pre_existing_final.team_id)

    async def test_rewrites_existing_tentative(self) -> None:
        """Re-running wire-from-groups with different seeding should overwrite
        previous TENTATIVE inputs, not duplicate them."""
        tournament_id = 99
        source = _group_stage(stage_id=1, tournament_id=tournament_id, num_groups=2)
        target = _playoff_stage(stage_id=2, tournament_id=tournament_id)

        # Slot 1 has an old TENTATIVE pointing to group B, position 2
        old_tentative = SimpleNamespace(
            slot=1,
            input_type=enums.StageItemInputType.TENTATIVE,
            team_id=None,
            source_stage_item_id=101,
            source_position=2,
        )
        target.items[0].inputs.append(old_tentative)

        added_inputs: list = []
        session = SimpleNamespace(
            add=Mock(side_effect=lambda obj: added_inputs.append(obj)),
            commit=AsyncMock(),
        )

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source, target]),
        ):
            await stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=2,
            )

        # The old tentative for slot 1 is updated in-place (not added to the DB)
        self.assertEqual(100, old_tentative.source_stage_item_id)  # A
        self.assertEqual(1, old_tentative.source_position)

        # Only 3 new inputs added (slots 2, 3, 4)
        self.assertEqual(3, len(added_inputs))
        self.assertEqual({2, 3, 4}, {inp.slot for inp in added_inputs})

    async def test_rejects_cross_tournament_stages(self) -> None:
        source = _group_stage(stage_id=1, tournament_id=99, num_groups=2)
        target = _playoff_stage(stage_id=2, tournament_id=100)  # different tournament

        session = SimpleNamespace(add=Mock(), commit=AsyncMock())

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source]),
        ):
            with self.assertRaises(Exception) as ctx:
                await stage_service.wire_from_groups(
                    session,
                    target_stage_id=target.id,
                    source_stage_id=source.id,
                    top=2,
                )

        self.assertIn("same tournament", str(ctx.exception))

    async def test_rejects_non_bracket_target(self) -> None:
        source = _group_stage(stage_id=1, tournament_id=99, num_groups=2)
        target = SimpleNamespace(
            id=2,
            tournament_id=99,
            stage_type=enums.StageType.ROUND_ROBIN,  # not a bracket
            items=[
                SimpleNamespace(id=200, name="Not a bracket", order=0, inputs=[])
            ],
        )

        session = SimpleNamespace(add=Mock(), commit=AsyncMock())

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source]),
        ):
            with self.assertRaises(Exception) as ctx:
                await stage_service.wire_from_groups(
                    session,
                    target_stage_id=target.id,
                    source_stage_id=source.id,
                    top=2,
                )

        self.assertIn("bracket", str(ctx.exception).lower())


class StageItemInputSchemaValidationTests(IsolatedAsyncioTestCase):
    async def test_tentative_requires_source(self) -> None:
        with self.assertRaises(Exception) as ctx:
            admin_schemas_module.StageItemInputCreate(
                slot=1,
                input_type=enums.StageItemInputType.TENTATIVE,
            )
        self.assertIn("source_stage_item_id", str(ctx.exception))

    async def test_tentative_rejects_team_id(self) -> None:
        with self.assertRaises(Exception) as ctx:
            admin_schemas_module.StageItemInputCreate(
                slot=1,
                input_type=enums.StageItemInputType.TENTATIVE,
                team_id=555,
                source_stage_item_id=10,
                source_position=1,
            )
        self.assertIn("must not have team_id", str(ctx.exception))

    async def test_final_requires_team_id(self) -> None:
        with self.assertRaises(Exception) as ctx:
            admin_schemas_module.StageItemInputCreate(
                slot=1,
                input_type=enums.StageItemInputType.FINAL,
            )
        self.assertIn("team_id", str(ctx.exception))

    async def test_final_with_team_id_ok(self) -> None:
        created = admin_schemas_module.StageItemInputCreate(
            slot=1,
            input_type=enums.StageItemInputType.FINAL,
            team_id=42,
        )
        self.assertEqual(42, created.team_id)

    async def test_tentative_with_source_ok(self) -> None:
        created = admin_schemas_module.StageItemInputCreate(
            slot=3,
            input_type=enums.StageItemInputType.TENTATIVE,
            source_stage_item_id=10,
            source_position=1,
        )
        self.assertEqual(10, created.source_stage_item_id)
        self.assertEqual(1, created.source_position)


def _de_stage_with_lb(
    *, stage_id: int, tournament_id: int, ub_item_id: int = 200, lb_item_id: int = 201
) -> SimpleNamespace:
    """Build a double-elimination stage with both UB and LB items."""
    return SimpleNamespace(
        id=stage_id,
        tournament_id=tournament_id,
        stage_type=enums.StageType.DOUBLE_ELIMINATION,
        items=[
            SimpleNamespace(
                id=ub_item_id,
                name="Upper Bracket",
                type=enums.StageItemType.BRACKET_UPPER,
                order=0,
                inputs=[],
            ),
            SimpleNamespace(
                id=lb_item_id,
                name="Lower Bracket",
                type=enums.StageItemType.BRACKET_LOWER,
                order=1,
                inputs=[],
            ),
        ],
    )


class SplitSeedingTests(IsolatedAsyncioTestCase):
    async def test_split_seeding_ub_and_lb(self) -> None:
        """top=2, top_lb=2 with 2 groups → 4 UB slots and 4 LB slots."""
        tournament_id = 99
        source = _group_stage(stage_id=1, tournament_id=tournament_id, num_groups=2)
        target = _de_stage_with_lb(stage_id=2, tournament_id=tournament_id)

        ub_inputs: list = []
        lb_inputs: list = []

        def _add(obj):
            if obj.stage_item_id == 200:
                ub_inputs.append(obj)
            else:
                lb_inputs.append(obj)

        session = SimpleNamespace(add=Mock(side_effect=_add), commit=AsyncMock())

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source, target]),
        ):
            await stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=2,
                top_lb=2,
            )

        # UB: positions 1-2 from each group (4 slots total)
        self.assertEqual(4, len(ub_inputs))
        ub_positions = {inp.source_position for inp in ub_inputs}
        self.assertEqual({1, 2}, ub_positions)

        # LB: positions 3-4 from each group (4 slots total)
        self.assertEqual(4, len(lb_inputs))
        lb_positions = {inp.source_position for inp in lb_inputs}
        self.assertEqual({3, 4}, lb_positions)

        # LB slots start from 1 in their own item
        self.assertEqual({1, 2, 3, 4}, {inp.slot for inp in lb_inputs})

    async def test_split_seeding_lb_positions_offset(self) -> None:
        """LB seeding picks positions top+1..top+top_lb, not 1..top_lb."""
        tournament_id = 99
        source = _group_stage(stage_id=1, tournament_id=tournament_id, num_groups=2)
        target = _de_stage_with_lb(stage_id=2, tournament_id=tournament_id)

        lb_inputs: list = []

        def _add(obj):
            if obj.stage_item_id == 201:
                lb_inputs.append(obj)

        session = SimpleNamespace(add=Mock(side_effect=_add), commit=AsyncMock())

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source, target]),
        ):
            await stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=3,
                top_lb=1,
            )

        # top=3, top_lb=1 → LB gets position 4 only
        self.assertEqual(2, len(lb_inputs))  # 2 groups × 1 position
        for inp in lb_inputs:
            self.assertEqual(4, inp.source_position)

    async def test_split_seeding_lb_requires_de_stage(self) -> None:
        """top_lb > 0 on a SINGLE_ELIMINATION stage must be rejected."""
        source = _group_stage(stage_id=1, tournament_id=99, num_groups=2)
        target = _playoff_stage(stage_id=2, tournament_id=99)  # single_elimination

        session = SimpleNamespace(add=Mock(), commit=AsyncMock())

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source]),
        ):
            with self.assertRaises(Exception) as ctx:
                await stage_service.wire_from_groups(
                    session,
                    target_stage_id=target.id,
                    source_stage_id=source.id,
                    top=2,
                    top_lb=2,
                )

        self.assertIn("double_elimination", str(ctx.exception).lower())

    async def test_split_seeding_lb_requires_lb_item(self) -> None:
        """top_lb > 0 when the DE stage has no BRACKET_LOWER item must be rejected."""
        source = _group_stage(stage_id=1, tournament_id=99, num_groups=2)
        # DE stage but only an UB item, no LB item
        target = SimpleNamespace(
            id=2,
            tournament_id=99,
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            items=[
                SimpleNamespace(
                    id=200,
                    name="Upper Bracket",
                    type=enums.StageItemType.BRACKET_UPPER,
                    order=0,
                    inputs=[],
                )
            ],
        )

        session = SimpleNamespace(add=Mock(), commit=AsyncMock())

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source]),
        ):
            with self.assertRaises(Exception) as ctx:
                await stage_service.wire_from_groups(
                    session,
                    target_stage_id=target.id,
                    source_stage_id=source.id,
                    top=2,
                    top_lb=2,
                )

        self.assertIn("BRACKET_LOWER", str(ctx.exception))

    async def test_split_seeding_zero_top_lb_unchanged(self) -> None:
        """top_lb=0 (default) should behave exactly like the original function."""
        tournament_id = 99
        source = _group_stage(stage_id=1, tournament_id=tournament_id, num_groups=2)
        target = _playoff_stage(stage_id=2, tournament_id=tournament_id)

        added_inputs: list = []
        session = SimpleNamespace(
            add=Mock(side_effect=lambda obj: added_inputs.append(obj)),
            commit=AsyncMock(),
        )

        with patch.object(
            stage_service,
            "get_stage",
            AsyncMock(side_effect=[target, source, target]),
        ):
            await stage_service.wire_from_groups(
                session,
                target_stage_id=target.id,
                source_stage_id=source.id,
                top=2,
                top_lb=0,
            )

        # Same result as existing test: 4 UB slots, no LB
        self.assertEqual(4, len(added_inputs))
        for inp in added_inputs:
            self.assertEqual(target.items[0].id, inp.stage_item_id)
