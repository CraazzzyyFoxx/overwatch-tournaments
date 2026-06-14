"""Level-adjusted performance helpers.

``Performance v2`` answers "how much did the player outperform the pre-match
expectation?".  This module adds a second interpretation layer:

    "how unusual is that performance for players of the same role and roughly
    the same division?"

The result stays separate from the absolute score so downstream consumers
(``Shift v2`` and player-anomaly detectors) can use both signals.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

__all__ = ("attach_local_performance",)


def _safe_std(values: pd.Series, *, fallback: float) -> float:
    std = float(values.astype(float).std(ddof=0)) if not values.empty else float("nan")
    if not math.isfinite(std) or std <= 1e-6:
        return max(float(fallback), 1.0)
    return std


def _percentile(values: pd.Series, raw_value: float) -> float:
    if values.empty:
        return 50.0
    return float((values.astype(float) <= float(raw_value)).mean() * 100.0)


def attach_local_performance(
    per_player: pd.DataFrame,
    *,
    initial_radius: int = 2,
    max_radius: int = 3,
    min_reference_n: int = 20,
    prior_strength: float = 20.0,
) -> pd.DataFrame:
    """Attach local-cohort performance statistics to a per-player frame.

    Required input columns:
    ``tournament_id``, ``player_id``, ``role``, ``division``, ``raw_value``.

    Baseline policy:
    - same tournament + same role,
    - adaptive division band ``±initial_radius`` expanding to ``±max_radius``,
    - if the selected band is still shallow, shrink its moments toward the
      tournament-wide same-role moments.
    """
    if per_player.empty:
        return per_player.assign(
            local_mean=pd.Series(dtype=float),
            local_std=pd.Series(dtype=float),
            local_residual=pd.Series(dtype=float),
            local_zscore=pd.Series(dtype=float),
            local_percentile=pd.Series(dtype=float),
            local_reference_n=pd.Series(dtype=int),
            local_band_min_div=pd.Series(dtype="Int64"),
            local_band_max_div=pd.Series(dtype="Int64"),
        )

    required = {"tournament_id", "player_id", "role", "division", "raw_value"}
    missing = required - set(per_player.columns)
    if missing:
        raise ValueError(f"missing columns for local performance: {sorted(missing)}")

    frame = per_player.copy()
    frame["division"] = pd.to_numeric(frame["division"], errors="coerce")
    frame["raw_value"] = pd.to_numeric(frame["raw_value"], errors="coerce").fillna(0.0)

    rows: list[dict[str, float | int | None]] = []
    grouped = frame.groupby(["tournament_id", "role"], dropna=False, sort=False)
    for (_, _), role_group in grouped:
        role_values = role_group["raw_value"].astype(float)
        role_mean = float(role_values.mean()) if not role_values.empty else 0.0
        role_std = _safe_std(role_values, fallback=1.0)

        for idx, row in role_group.iterrows():
            division = row["division"]
            raw_value = float(row["raw_value"])

            if pd.isna(division):
                reference = role_group[role_group.index != idx]
                radius = None
                band_min = None
                band_max = None
            else:
                reference = role_group.iloc[0:0]
                radius = initial_radius
                for candidate_radius in range(initial_radius, max_radius + 1):
                    candidate = role_group[
                        role_group["division"].between(
                            float(division) - candidate_radius,
                            float(division) + candidate_radius,
                        )
                        & (role_group.index != idx)
                    ]
                    reference = candidate
                    radius = candidate_radius
                    if len(candidate) >= min_reference_n:
                        break
                band_min = int(float(division) - radius)
                band_max = int(float(division) + radius)

            # Empty/sparse bands still get a stable cohort by falling back to
            # all same-role peers in the tournament, then shrinking moments
            # toward the same-role global moments.
            if reference.empty:
                reference = role_group[role_group.index != idx]

            ref_values = reference["raw_value"].astype(float)
            local_n = int(len(ref_values))
            local_mean = float(ref_values.mean()) if local_n else role_mean
            local_std_raw = _safe_std(ref_values, fallback=role_std)

            alpha = (
                float(local_n) / (float(local_n) + float(prior_strength))
                if local_n > 0
                else 0.0
            )
            shrunk_mean = alpha * local_mean + (1.0 - alpha) * role_mean
            shrunk_std = alpha * local_std_raw + (1.0 - alpha) * role_std
            shrunk_std = max(float(shrunk_std), 1e-6)

            residual = raw_value - shrunk_mean
            zscore = residual / shrunk_std
            percentile_pool = role_group[
                role_group["division"].between(band_min, band_max)
            ]["raw_value"] if band_min is not None and band_max is not None else role_values

            rows.append(
                {
                    "_index": idx,
                    "local_mean": float(shrunk_mean),
                    "local_std": float(shrunk_std),
                    "local_residual": float(residual),
                    "local_zscore": float(zscore),
                    "local_percentile": _percentile(percentile_pool, raw_value),
                    "local_reference_n": local_n,
                    "local_band_min_div": band_min,
                    "local_band_max_div": band_max,
                }
            )

    local = pd.DataFrame(rows).set_index("_index")
    for column in (
        "local_mean",
        "local_std",
        "local_residual",
        "local_zscore",
        "local_percentile",
        "local_reference_n",
        "local_band_min_div",
        "local_band_max_div",
    ):
        frame[column] = local[column]
    return frame.replace([np.inf, -np.inf], np.nan)
