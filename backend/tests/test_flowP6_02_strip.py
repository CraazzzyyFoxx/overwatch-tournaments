"""flowP6_02 strips the league params from stored condition trees (spec §11.5)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "flowP6_02_drop_is_league.py"
_spec = importlib.util.spec_from_file_location("flowP6_02", _PATH)
assert _spec is not None and _spec.loader is not None
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def test_league_params_are_stripped_at_any_depth() -> None:
    tree = {
        "AND": [
            {"type": "tournament_type", "params": {"is_league": False}},
            {
                "OR": [
                    {"type": "standing_count", "params": {"op": ">=", "value": 3, "is_league": None}},
                    {"NOT": {"type": "global_winrate", "params": {"metric": "won_maps", "include_league": True}}},
                ]
            },
        ]
    }
    stripped, changed = migration.strip_league_params(tree)
    assert changed is True
    assert stripped == {
        "AND": [
            {"type": "tournament_type", "params": {}},
            {
                "OR": [
                    {"type": "standing_count", "params": {"op": ">=", "value": 3}},
                    {"NOT": {"type": "global_winrate", "params": {"metric": "won_maps"}}},
                ]
            },
        ]
    }


def test_a_tree_without_league_params_is_unchanged() -> None:
    tree = {"type": "tournament_count", "params": {"op": ">=", "value": 10}}
    assert migration.strip_league_params(tree) == (tree, False)
    assert migration.strip_league_params({}) == ({}, False)
