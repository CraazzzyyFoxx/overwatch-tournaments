"""What a fresh ``tournament.stage`` row holds for its regulation, for test doubles.

``SimpleNamespace(**stage_regulation(...), stage_type=...)`` stands in for a
stage the engine reads.

Levels 1-2 of the scoring live in ``encounter.scoring_rule`` now (D51), so the
double carries a ``scoring_rule`` namespace rather than the ``ffa_*`` columns:
``compile_rules`` reads ``preset``/``columns``/``placement_points``/
``game_formula``/``end_formula`` off it and never touches the stage again. The
old ``ffa_columns`` / ``ffa_formula`` / ``ffa_placement_points`` keyword names
are still accepted and fold into that rule, because they are how the cases that
use this helper spell "what this stage records and pays".
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

#: The ``wins`` preset, as ``enclayer01`` writes it into every duel stage's row.
WINS_END_FORMULA = "games >= best_of or max_wins * 2 > best_of"
POINTS_END_FORMULA = "games >= best_of"

_DEFAULT_COLUMNS = [{"key": "score", "label": "Score", "public": True, "better": "higher"}]


def scoring_rule(
    *,
    preset: str = "points",
    columns: list[dict[str, Any]] | None = None,
    placement_points: list[float] | None = None,
    formula: str = "score",
) -> SimpleNamespace:
    """One ``encounter.scoring_rule`` row as a double.

    Defaults to the ``points`` preset: every case that reaches for this helper's
    scoring is a lobby stage, and a bracket stage's rule is never read by the
    ranking (its table is built from places, not from column sums).
    """
    return SimpleNamespace(
        preset=preset,
        columns=_DEFAULT_COLUMNS if columns is None else columns,
        placement_points=list(placement_points or ()),
        game_formula=formula,
        end_formula=POINTS_END_FORMULA if preset == "points" else WINS_END_FORMULA,
    )


def stage_regulation(*, by_round: dict[int, int] | None = None, **overrides: Any) -> dict[str, Any]:
    rule_overrides = {
        "columns": overrides.pop("ffa_columns", None),
        "placement_points": overrides.pop("ffa_placement_points", None),
        "formula": overrides.pop("ffa_formula", "score"),
    }
    values: dict[str, Any] = {
        "ranking_preset": None,
        "tiebreak_order": None,
        "win_points": None,
        "draw_points": None,
        "loss_points": None,
        "swiss_bye_points": None,
        "swiss_qualify_wins": None,
        "swiss_eliminate_losses": None,
        "de_grand_final_type": "no_reset",
        "seed_ranking": "slot",
        "best_of_default": 3,
        "best_of_final": None,
        "best_of_swiss_qualify": None,
        "best_of_swiss_eliminate": None,
        "round_best_of": [],
        "scoring_rule": overrides.pop("scoring_rule", None) or scoring_rule(**rule_overrides),
        "scoring_rule_id": 1,
        "challonge_group_id": None,
        "bracket_template": None,
        "rank_win_delta": None,
        "rank_loss_delta": None,
    }
    values.update(overrides)
    if by_round:
        values["round_best_of"] = [
            SimpleNamespace(round=round_number, best_of=best_of) for round_number, best_of in sorted(by_round.items())
        ]
    return values
