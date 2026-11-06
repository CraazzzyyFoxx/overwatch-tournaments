"""The pure stored-rule rewrite inside the ``flowP1_participant_result`` revision (loaded by path: migrations do not
import ``shared``)."""

from __future__ import annotations

import importlib.util
import pathlib
from typing import Any

_VERSIONS = pathlib.Path(__file__).resolve().parents[1] / "migrations" / "versions"


def _load(name: str, path: pathlib.Path) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = _load("flowP1_participant_result", _VERSIONS / "flowP1_participant_result.py")


def test_include_groups_is_dropped_from_standing_position_only() -> None:
    tree = {
        "AND": [
            {"type": "standing_position", "params": {"op": "==", "value": 1, "include_groups": True}},
            {"type": "standing_record", "params": {"field": "wins", "op": ">=", "value": 3, "include_groups": True}},
        ]
    }
    rewritten, changed = mod._strip_include_groups(tree)
    assert changed is True
    assert rewritten == {
        "AND": [
            {"type": "standing_position", "params": {"op": "==", "value": 1}},
            {"type": "standing_record", "params": {"field": "wins", "op": ">=", "value": 3, "include_groups": True}},
        ]
    }


def test_a_tree_without_the_param_is_unchanged() -> None:
    tree = {"type": "standing_position", "params": {"op": "<=", "value": 2}}
    assert mod._strip_include_groups(tree) == (tree, False)


def test_rules_reading_participant_result_are_found_at_any_depth() -> None:
    nested = {"OR": [{"type": "log_stat_rank", "params": {}}, {"AND": [{"type": "consecutive", "params": {}}]}]}
    assert mod._reads_participant_result(nested) is True
    assert mod._reads_participant_result({"type": "log_stat_rank", "params": {"stat": "KD"}}) is False
