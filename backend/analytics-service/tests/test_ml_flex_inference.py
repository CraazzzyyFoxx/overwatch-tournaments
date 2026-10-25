"""Inference for a flex tournament, whose players hold no rated role (production tournament 84)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd

from src.services.ml.inference import runner
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


def test_a_flex_player_without_performance_figures_gets_a_shift_row_with_zero_evidence() -> None:
    # No rated role means no Performance v2 row, so the merged evidence columns are NaN for this player.
    frame = pd.DataFrame(
        {
            "tournament_id": [84, 84],
            "player_id": [1, 2],
            "match_count": [np.nan, 6.0],
            "tournaments_played": [np.nan, 3.0],
            "log_coverage": [np.nan, 0.5],
        }
    )
    model = SimpleNamespace(
        predict_with_uncertainty=lambda df: pd.DataFrame({"shift_v2": [0.4, -0.2], "shift_sd": [0.9, 0.6]})
    )
    exports = SimpleNamespace(MODELS={"shift": SimpleNamespace(algorithm_name="OpenSkill + ML", model_kind="shift")})
    session = SimpleNamespace(execute=AsyncMock(), commit=AsyncMock())

    with (
        patch.object(runner, "tournament_module", AsyncMock(return_value=("overwatch", exports))),
        patch.object(runner, "_algorithm_id", AsyncMock(return_value=17)),
        patch.object(
            runner.registry_service, "load_active_artifact", AsyncMock(return_value=SimpleNamespace(storage_uri="f"))
        ),
        patch.object(runner, "load_artifact_or_none", return_value=model),
        patch.object(runner, "build_shift_feature_frame", AsyncMock(return_value=frame)),
    ):
        written = asyncio.run(runner.run_shift_for_tournament(session, 84, workspace_id=6))

    assert written == 2
    rows = {row["player_id"]: row for row in session.execute.await_args_list[-1].args[1]}
    assert (rows[1]["effective_evidence"], rows[1]["sample_tournaments"], rows[1]["sample_matches"]) == (0.0, 0, 0)
    assert rows[1]["log_coverage"] == 0.0
    assert (rows[2]["sample_tournaments"], rows[2]["sample_matches"], rows[2]["log_coverage"]) == (3, 6, 0.5)
