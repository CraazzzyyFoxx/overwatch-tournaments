"""What a fresh ``tournament.stage`` row holds for its regulation, for test doubles.

``SimpleNamespace(**stage_regulation(...), stage_type=...)`` stands in for a
stage the engine reads; ``models.Stage(**stage_regulation(...), ...)`` works too
as long as ``by_round`` is not used (its rows are plain namespaces, not ORM
``StageRoundBestOf`` objects).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def stage_regulation(*, by_round: dict[int, int] | None = None, **overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "ranking_preset": None,
        "tiebreak_order": None,
        "win_points": None,
        "draw_points": None,
        "loss_points": None,
        "swiss_bye_points": None,
        "de_grand_final_type": "no_reset",
        "seed_ranking": "slot",
        "best_of_default": 3,
        "best_of_final": None,
        "round_best_of": [],
        "ffa_placement_points": [],
        "ffa_score_points": 1.0,
        "ffa_score_label": None,
        "challonge_group_id": None,
    }
    values.update(overrides)
    if by_round:
        values["round_best_of"] = [
            SimpleNamespace(round=round_number, best_of=best_of) for round_number, best_of in sorted(by_round.items())
        ]
    return values
