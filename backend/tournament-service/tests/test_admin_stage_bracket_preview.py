"""`get_bracket_preview` must return the bracket the generator would build --
the admin Bracket tab draws it with the SAME view the public page uses, so a
shape re-derived in the frontend would be a second, disagreeing generator.

Pins the properties the drawing depends on: one row per pairing, the real
per-round match counts, wired teams under their own names, advancement edges as
skeleton-local ``sources``, and every slot TBD on a playoff that is only
projected from its preceding group stage.

Does not touch a real database: ``get_stage`` and ``_load_team_names`` are
patched directly (the pattern of ``test_admin_stage_planned_rounds.py``).
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

stage_service = importlib.import_module("src.services.admin.stage")
enums = importlib.import_module("shared.core.enums")

from tests._stage_regulation import stage_regulation  # noqa: E402

service = stage_service.stage_service


def _input(team_id: int | None, slot: int) -> SimpleNamespace:
    return SimpleNamespace(team_id=team_id, slot=slot)


def _item(
    item_id: int,
    inputs: list[SimpleNamespace],
    *,
    order: int = 0,
    item_type=enums.StageItemType.SINGLE_BRACKET,
) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, order=order, inputs=inputs, type=item_type)


def _matches_per_round(matches: list[dict]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for match in matches:
        counts[match["round"]] = counts.get(match["round"], 0) + 1
    return counts


class GetBracketPreviewTests(IsolatedAsyncioTestCase):
    async def test_draws_a_seeded_single_elimination_with_names_and_edges(self) -> None:
        stage = SimpleNamespace(
            **stage_regulation(),
            id=5,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, [_input(team_id, team_id) for team_id in range(1, 9)])],
        )
        names = {team_id: f"Team {team_id}" for team_id in range(1, 9)}

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service, "_load_team_names", AsyncMock(return_value=names)),
        ):
            preview = await service.get_bracket_preview(SimpleNamespace(), 5)

        matches = preview["matches"]
        # 8 teams -> 4 + 2 + 1.
        self.assertEqual({1: 4, 2: 2, 3: 1}, _matches_per_round(matches))
        self.assertEqual(sorted(range(1, len(matches) + 1)), sorted(m["local_id"] for m in matches))
        # Seeded slots carry their team, and the name the generator would write.
        first = next(m for m in matches if m["round"] == 1)
        self.assertEqual("Team 1 vs Team 8", first["name"])
        self.assertEqual(3, first["best_of"])
        # A later round is fed by winners of earlier rows of this same response.
        final = next(m for m in matches if m["round"] == 3)
        self.assertEqual(
            [("winner", "home"), ("winner", "away")],
            [(source["role"], source["slot"]) for source in final["sources"]],
        )
        local_ids = {match["local_id"] for match in matches}
        for source in final["sources"]:
            self.assertIn(source["local_id"], local_ids)

    async def test_projects_an_unseeded_playoff_with_every_slot_tbd(self) -> None:
        # No teams wired: same fallback generation takes -- advance_count (4)
        # from each of 2 groups, split into a 4-team upper bracket and 4 lower
        # seeds -- so the drawn tree is the one that will be generated.
        stage = SimpleNamespace(
            **stage_regulation(),
            id=5,
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            items=[_item(1, [])],
            split_lower_bracket=True,
        )
        source = SimpleNamespace(id=4, advance_count=4, items=[_item(10, []), _item(11, [])])

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service, "_preceding_group_stage", AsyncMock(return_value=source)),
            patch.object(service, "_load_team_names", AsyncMock(return_value={})),
        ):
            preview = await service.get_bracket_preview(SimpleNamespace(), 5)

        matches = preview["matches"]
        self.assertEqual([-4, -3, -2, -1, 1, 2, 3], sorted(_matches_per_round(matches)))
        for match in matches:
            self.assertIsNone(match["home_team_id"])
            self.assertIsNone(match["away_team_id"])
            self.assertEqual("TBD vs TBD", match["name"])
        # Only edges make an unseeded bracket readable ("W M3"), so they must
        # survive the placeholder path.
        self.assertTrue(any(match["sources"] for match in matches))

    async def test_a_group_stage_has_no_bracket_to_draw(self) -> None:
        stage = SimpleNamespace(
            **stage_regulation(),
            id=5,
            stage_type=enums.StageType.SWISS,
            items=[_item(1, [_input(1, 1), _input(2, 2)])],
        )

        with patch.object(service, "get_stage", AsyncMock(return_value=stage)):
            preview = await service.get_bracket_preview(SimpleNamespace(), 5)

        self.assertEqual([], preview["matches"])

    async def test_nothing_to_draw_without_seeds_or_an_upstream_group_stage(self) -> None:
        stage = SimpleNamespace(
            **stage_regulation(),
            id=5,
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            items=[_item(1, [_input(1, 1)])],
        )

        with (
            patch.object(service, "get_stage", AsyncMock(return_value=stage)),
            patch.object(service, "_preceding_group_stage", AsyncMock(return_value=None)),
        ):
            preview = await service.get_bracket_preview(SimpleNamespace(), 5)

        self.assertEqual([], preview["matches"])
