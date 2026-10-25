"""SHAP explanations for a tournament whose players hold no rated role."""

from __future__ import annotations

import pandas as pd

from src.services.ml.inference.runner import _shap_by_player


def test_a_flex_tournament_without_rated_roles_gets_no_explanations_instead_of_failing() -> None:
    # A flex tournament resolves no rated role for anyone: every feature row carries role None.
    feature_frame = pd.DataFrame(
        {
            "player_id": [1, 1, 2],
            "role": [None, None, None],
            "eliminations": [10.0, 12.0, 8.0],
        }
    )
    per_player = pd.DataFrame({"player_id": [1, 2], "tournament_id": [84, 84]})

    # The models are never reached: no row has a role to explain it with.
    assert _shap_by_player(per_player, feature_frame, {"tank": object(), "support": object()}) == {}
