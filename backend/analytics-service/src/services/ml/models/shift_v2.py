"""Shift v2 ("OpenSkill + ML") — team-result backbone + additive individual skill.

Prod analysis showed the **team result** (W/L vs the balanced seeding) is by far
the strongest predictor of realised division moves. So the backbone is a
team-dominant convex mix of the v1 team-result Linear shift and the OpenSkill mu
shift. On top of it an **additive individual skill term** lifts players whose
individual signal is far from their cohort. It is the MAX of two channels:
``local_zscore`` (skill vs same role + nearby division, softly clamped per
division) and a **raw match-log MVP dominance** lift. The dominance channel is a
first-class signal bounded only by the rank/grid output clamp (not the softer
local clamp), so a consistent scoreboard-topper that the expectation-adjusted
impact under-credits is pushed to their rank-appropriate ceiling. The positive
individual lift is then **gated by the team's final placement** — scaled down
toward zero for a last-placed team — so strong individual play on a losing team
does not earn a promotion. A clear individual outlier therefore moves even when
the team result doesn't capture it, instead of being averaged away:

    shift_v2 = clamp( w_team·team_result + w_os·os_shift
                      + clip(scale(div)·local_zscore, ±clamp(div)) ,
                      ±out_clamp(div, grid) )

The individual term's scale/clamp are **rank-dependent**: the same +N move is a
far bigger claim near the ceiling (sparse cohort, steep real skill-per-SR, hard
cap) than mid-ladder, so ``scale``/``clamp`` ramp linearly with the canonical
division number — small at the top (division 1), full at the bottom — instead of
applying one flat factor to everyone.

The **output clamp itself is rank- AND grid-dependent**: the individual damping
alone can't hold a high-rank player whose team/OS backbone (e.g. a large
OpenSkill mu jump) already pushes toward ±3. So the final clamp is squeezed at
the top of the ladder and the top cap scales with the workspace grid's division
count — ``grid_n_div / clamp_top_grid_ref`` (a 20-division grid → ±1 at the top,
a 40-division grid → ±2) so the cap means the same *real* rank distance
regardless of granularity — ramping back up to the full ``shift_range`` at the
bottom. A high-rank player therefore can't be yanked ±3 by one tournament from
any source, while low ranks still move freely.

There is no learned regression toward the (mostly-zero) realised move — that
collapsed the signal. Weights/scales are fixed (config-tunable) and snapshotted
into the artifact at train time. Newcomers (no prior tournament) get the clipped
team backbone only (no individual term — one tournament is too noisy).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from shared.division_grid import DEFAULT_GRID

from .base import MLModel

__all__ = (
    "ShiftModelV2",
    "ShiftTrainingResult",
    "train_shift_v2",
)

logger = logging.getLogger(__name__)

# Output bounds. ``SHIFT_RANGE`` is the bottom-of-ladder (low rank) clamp; the
# top of the ladder is squeezed to ``grid_n_div / CLAMP_TOP_GRID_REF`` divisions
# (a 20-division grid → 1.0, a 40-division grid → 2.0) so the cap means the same
# real rank distance regardless of grid granularity. The clamp ramps between the
# two by canonical division number.
SHIFT_RANGE: float = 3.0
CLAMP_TOP_GRID_REF: float = 20.0
NEWCOMER_SHIFT_RANGE: float = 1.5

# Blend defaults (team-dominant backbone; additive individual skill term).
BLEND_W_TEAM: float = 0.7
BLEND_W_OS: float = 0.3
# Individual skill modifier — RANK-DEPENDENT scale/clamp (divisions per std-dev
# of, and max |modifier| in, divisions). ``_TOP`` applies at the highest rank
# (canonical division 1, near the ceiling) and ``_BOTTOM`` at the lowest. The
# same outlier therefore moves much less near the top (sparse, high-variance,
# capped) than mid/low ladder where over-/under-ranking is common and cheap.
INDIV_MOD_SCALE_TOP: float = 0.2
INDIV_MOD_SCALE_BOTTOM: float = 0.8
INDIV_MOD_CLAMP_TOP: float = 0.75
INDIV_MOD_CLAMP_BOTTOM: float = 2.0

# Raw match-log MVP dominance lift. ``mvp_dominance`` ∈ [0,1] (0.5 = median) is
# turned into a non-negative z-like signal, then MAX-blended with the local term
# and bounded ONLY by the rank/grid output clamp (not the softer per-division
# local clamp) — so a consistent scoreboard-topper that expectation-adjusted
# impact under-credits is pushed to their rank-appropriate ceiling. Only lifts
# (never lowers); high ranks stay protected by the tight output clamp.
DOMINANCE_PIVOT: float = 0.5
DOMINANCE_GAIN: float = 6.0
DOMINANCE_CAP: float = 3.0

# Team final-placement gate on the POSITIVE individual lift. The lift is scaled
# by a factor ∈ [PLACEMENT_FLOOR, 1] — 1.0 for the tournament winner, ramping to
# the floor for last place — so strong individual play on a last-placed team is
# not promoted. Floor 0.0 = full gate at last place.
PLACEMENT_FLOOR: float = 0.0

# Canonical OW grid bounds (number 1 = top … 40 = bottom); the ramp is keyed on
# the division number so it stays comparable across workspace grids.
_GRID_MIN_DIV: float = float(DEFAULT_GRID.min_division)
_GRID_MAX_DIV: float = float(DEFAULT_GRID.max_division)
_GRID_MID_DIV: float = (_GRID_MIN_DIV + _GRID_MAX_DIV) / 2.0

# Columns the blend reads (for MLModel/feature introspection).
SHIFT_BLEND_COLUMNS: tuple[str, ...] = (
    "linear_stable_shift",
    "os_shift",
    "performance_v2_local_zscore",
)


def _team_result(df: pd.DataFrame) -> pd.Series:
    """Team-result backbone component: v1 Linear ``stable_shift`` (fallback os_shift)."""
    fallback = pd.to_numeric(
        df.get("os_shift", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)
    if "linear_stable_shift" not in df.columns:
        return fallback
    stable = pd.to_numeric(df["linear_stable_shift"], errors="coerce")
    return stable.where(stable.notna(), fallback).fillna(0.0)


def _os_shift(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(
        df.get("os_shift", pd.Series(0.0, index=df.index)), errors="coerce"
    ).fillna(0.0)


def _rank_ramp(div: pd.Series, *, top: float, bottom: float) -> pd.Series:
    """Linear ramp on the canonical division number (1 = top … 40 = bottom).

    Returns ``top`` at the highest rank (division 1) and ``bottom`` at the lowest;
    rows with an unknown division fall back to the mid-ladder value (neutral).
    """
    d = pd.to_numeric(div, errors="coerce").fillna(_GRID_MID_DIV)
    span = (_GRID_MAX_DIV - _GRID_MIN_DIV) or 1.0
    t = ((d - _GRID_MIN_DIV) / span).clip(0.0, 1.0)
    return top + (bottom - top) * t


def _output_clamp(
    df: pd.DataFrame,
    *,
    shift_range: float,
    top_grid_ref: float,
) -> pd.Series:
    """Per-row rank- and grid-dependent output clamp.

    Top of the ladder (canonical division 1) is capped at
    ``grid_n_div / top_grid_ref`` divisions (a 20-division grid → 1.0, a 40 → 2.0)
    so the cap means the same real rank distance regardless of granularity; the
    cap ramps up to ``shift_range`` at the bottom (division 40). Missing grid size
    falls back to the canonical 40-tier grid; missing division → mid-ladder.
    """
    div = pd.to_numeric(
        df.get("current_div", pd.Series(np.nan, index=df.index)), errors="coerce"
    ).fillna(_GRID_MID_DIV)
    n_div = pd.to_numeric(
        df.get("grid_n_div", pd.Series(_GRID_MAX_DIV, index=df.index)), errors="coerce"
    ).fillna(_GRID_MAX_DIV)
    ref = top_grid_ref or 1.0
    top_cap = (n_div / ref).clip(lower=0.0, upper=shift_range)
    span = (_GRID_MAX_DIV - _GRID_MIN_DIV) or 1.0
    t = ((div - _GRID_MIN_DIV) / span).clip(0.0, 1.0)
    return top_cap + (shift_range - top_cap) * t


def _dominance_z(df: pd.DataFrame, *, gain: float, cap: float) -> pd.Series:
    """Raw MVP dominance turned into a non-negative z-like lift.

    ``mvp_dominance`` ∈ [0,1] (0.5 = median scoreboard position). Above the pivot
    it lifts (``(dom-0.5)*gain``, capped); at/below it contributes nothing — a low
    scoreboard position must not push a player *down* (that is the team result's
    job). Neutral (0) where there is no match log.
    """
    dom = pd.to_numeric(
        df.get("mvp_dominance", pd.Series(DOMINANCE_PIVOT, index=df.index)),
        errors="coerce",
    ).fillna(DOMINANCE_PIVOT)
    return ((dom - DOMINANCE_PIVOT) * gain).clip(lower=0.0, upper=cap)


def _placement_factor(df: pd.DataFrame, *, floor: float) -> pd.Series:
    """Team final-placement gate ∈ [floor, 1] for the positive individual lift.

    1.0 for the tournament winner, ramping to ``floor`` for last place — so a
    strong individual on a last-placed team is not promoted. Missing standings
    (no ``overall_position``/``team_count``) → 1.0 (no gate).
    """
    pos = pd.to_numeric(
        df.get("overall_position", pd.Series(np.nan, index=df.index)), errors="coerce"
    )
    n = pd.to_numeric(
        df.get("team_count", pd.Series(np.nan, index=df.index)), errors="coerce"
    )
    raw = ((n - pos) / (n - 1.0).clip(lower=1.0)).clip(0.0, 1.0)
    factor = floor + (1.0 - floor) * raw
    return factor.where(pos.notna() & n.notna() & (n > 1), 1.0)


def _indiv_mod(
    df: pd.DataFrame,
    *,
    scale_top: float,
    scale_bottom: float,
    clamp_top: float,
    clamp_bottom: float,
) -> pd.Series:
    """Local-cohort individual term: ``clip(scale(div)·local_zscore, ±clamp(div))``.

    ``local_zscore`` is the player's skill vs the same role + nearby division
    cohort. Both scale and clamp ramp by canonical division — small near the
    ceiling (a +N there is a sparse, high-variance, capped claim), full mid/low
    ladder. The raw scoreboard-dominance lift is applied separately (and bounded
    only by the output clamp), so this softer per-division clamp governs only the
    noisier expectation-adjusted cohort signal.
    """
    z = pd.to_numeric(
        df.get("performance_v2_local_zscore", pd.Series(0.0, index=df.index)),
        errors="coerce",
    ).fillna(0.0)
    div = df.get("current_div", pd.Series(np.nan, index=df.index))
    scale = _rank_ramp(div, top=scale_top, bottom=scale_bottom)
    clamp = _rank_ramp(div, top=clamp_top, bottom=clamp_bottom)
    return (scale * z).clip(lower=-clamp, upper=clamp)


def _linear_confidence(df: pd.DataFrame) -> pd.Series:
    if "linear_confidence" not in df.columns:
        return pd.Series(0.0, index=df.index)
    return pd.to_numeric(df["linear_confidence"], errors="coerce").fillna(0.0).clip(0.0, 1.0)


def _newcomer_mask(df: pd.DataFrame) -> np.ndarray:
    is_newcomer = df.get("is_newcomer", pd.Series(False, index=df.index))
    played = pd.to_numeric(
        df.get("tournaments_played", pd.Series(0, index=df.index)), errors="coerce"
    ).fillna(0)
    return (is_newcomer.fillna(False).astype(bool) | (played <= 1)).to_numpy()


@dataclass
class ShiftModelV2(MLModel):
    """Team-result backbone + additive individual-skill modifier (no regression)."""

    w_team: float = BLEND_W_TEAM
    w_os: float = BLEND_W_OS
    indiv_scale_top: float = INDIV_MOD_SCALE_TOP
    indiv_scale_bottom: float = INDIV_MOD_SCALE_BOTTOM
    indiv_clamp_top: float = INDIV_MOD_CLAMP_TOP
    indiv_clamp_bottom: float = INDIV_MOD_CLAMP_BOTTOM
    dominance_gain: float = DOMINANCE_GAIN
    dominance_cap: float = DOMINANCE_CAP
    placement_floor: float = PLACEMENT_FLOOR
    shift_range: float = SHIFT_RANGE
    clamp_top_grid_ref: float = CLAMP_TOP_GRID_REF
    feature_order: list[str] = field(default_factory=lambda: list(SHIFT_BLEND_COLUMNS))

    def _shift_array(self, df: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        backbone = (
            self.w_team * _team_result(df).to_numpy()
            + self.w_os * _os_shift(df).to_numpy()
        )
        # Rank- and grid-dependent output clamp: squeezed at the top of the
        # ladder so no source (backbone or individual) can yank a high-rank player
        # the full range from one tournament; top cap scales with grid size.
        # getattr fallbacks let artifacts pickled before these fields load and
        # degrade to the current code defaults instead of erroring.
        out_clamp = _output_clamp(
            df,
            shift_range=self.shift_range,
            top_grid_ref=getattr(self, "clamp_top_grid_ref", CLAMP_TOP_GRID_REF),
        ).to_numpy()
        # Local-cohort term — softer per-division clamp on the noisier
        # expectation-adjusted ``local_zscore``.
        z_term = _indiv_mod(
            df,
            scale_top=getattr(self, "indiv_scale_top", INDIV_MOD_SCALE_TOP),
            scale_bottom=getattr(self, "indiv_scale_bottom", INDIV_MOD_SCALE_BOTTOM),
            clamp_top=getattr(self, "indiv_clamp_top", INDIV_MOD_CLAMP_TOP),
            clamp_bottom=getattr(self, "indiv_clamp_bottom", INDIV_MOD_CLAMP_BOTTOM),
        ).to_numpy()
        # Raw scoreboard-dominance term — a first-class signal bounded ONLY by the
        # rank/grid output clamp (not the softer local clamp), so a consistent
        # match-MVP is pushed to their rank-appropriate ceiling. High ranks stay
        # protected because the output clamp is tight there.
        dom_z = _dominance_z(
            df,
            gain=getattr(self, "dominance_gain", DOMINANCE_GAIN),
            cap=getattr(self, "dominance_cap", DOMINANCE_CAP),
        ).to_numpy()
        dom_term = np.clip(dom_z, 0.0, out_clamp)
        indiv = np.maximum(z_term, dom_term)
        # Gate the POSITIVE individual lift by the team's final placement — strong
        # individual play on a last-placed team must not earn a promotion. A
        # downward individual signal is placement-independent.
        placement = _placement_factor(
            df, floor=getattr(self, "placement_floor", PLACEMENT_FLOOR)
        ).to_numpy()
        indiv = np.where(indiv > 0.0, indiv * placement, indiv)
        shift = np.clip(backbone + indiv, -out_clamp, out_clamp)
        # Newcomers: team backbone only (one tournament of individual signal is
        # too noisy), clipped to the conservative newcomer range but never looser
        # than the rank/grid output clamp.
        newcomer = _newcomer_mask(df)
        newcomer_clamp = np.minimum(NEWCOMER_SHIFT_RANGE, out_clamp)
        shift = np.where(
            newcomer,
            np.clip(backbone, -newcomer_clamp, newcomer_clamp),
            shift,
        )
        return shift, newcomer

    def predict(self, df: pd.DataFrame) -> pd.Series:
        if df.empty:
            return pd.Series(dtype=float)
        shift, _ = self._shift_array(df)
        return pd.Series(shift, index=df.index, name="shift_v2")

    def predict_with_confidence(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return pd.DataFrame(columns=["shift_v2", "confidence"], dtype=float)
        shift, newcomer = self._shift_array(df)
        confidence = _linear_confidence(df).to_numpy()
        confidence = np.where(newcomer, confidence * 0.5, confidence)
        return pd.DataFrame(
            {"shift_v2": shift, "confidence": np.clip(confidence, 0.0, 1.0)},
            index=df.index,
        )


@dataclass
class ShiftTrainingResult:
    model: ShiftModelV2
    metrics: dict[str, float]
    feature_importance: dict[str, float]


def train_shift_v2(
    df: pd.DataFrame,
    *,
    val_df: pd.DataFrame | None = None,
    w_team: float = BLEND_W_TEAM,
    w_os: float = BLEND_W_OS,
    indiv_scale_top: float = INDIV_MOD_SCALE_TOP,
    indiv_scale_bottom: float = INDIV_MOD_SCALE_BOTTOM,
    indiv_clamp_top: float = INDIV_MOD_CLAMP_TOP,
    indiv_clamp_bottom: float = INDIV_MOD_CLAMP_BOTTOM,
    dominance_gain: float = DOMINANCE_GAIN,
    dominance_cap: float = DOMINANCE_CAP,
    placement_floor: float = PLACEMENT_FLOOR,
    clamp_top_grid_ref: float = CLAMP_TOP_GRID_REF,
) -> ShiftTrainingResult:
    """Snapshot the (config-tunable) blend weights into a model artifact.

    There is no learned fit — the data showed regressing the sparse realised move
    collapses the signal and an NNLS fit drifted to an unstable os-heavy solution.
    Weights/scales come from config; this just builds the model and reports a
    diagnostic MAE of the blend vs the realised move on any labelled rows.
    """
    if df.empty:
        raise ValueError("training DataFrame is empty")
    model = ShiftModelV2(
        w_team=w_team,
        w_os=w_os,
        indiv_scale_top=indiv_scale_top,
        indiv_scale_bottom=indiv_scale_bottom,
        indiv_clamp_top=indiv_clamp_top,
        indiv_clamp_bottom=indiv_clamp_bottom,
        dominance_gain=dominance_gain,
        dominance_cap=dominance_cap,
        placement_floor=placement_floor,
        clamp_top_grid_ref=clamp_top_grid_ref,
    )

    metrics: dict[str, float] = {
        "n_rows": float(len(df)),
        "w_team": w_team,
        "w_os": w_os,
        "indiv_scale_top": indiv_scale_top,
        "indiv_scale_bottom": indiv_scale_bottom,
        "indiv_clamp_top": indiv_clamp_top,
        "indiv_clamp_bottom": indiv_clamp_bottom,
        "dominance_gain": dominance_gain,
        "dominance_cap": dominance_cap,
        "placement_floor": placement_floor,
        "clamp_top_grid_ref": clamp_top_grid_ref,
    }

    def _mae_vs_realised(frame: pd.DataFrame) -> tuple[float, int] | None:
        if any(c not in frame.columns for c in ("current_div", "next_tournament_div")):
            return None
        labelled = frame.dropna(subset=["current_div", "next_tournament_div"])
        if labelled.empty:
            return None
        realised = (
            labelled["current_div"].astype(float)
            - labelled["next_tournament_div"].astype(float)
        ).to_numpy()
        pred = model.predict(labelled).to_numpy()
        return float(np.mean(np.abs(pred - realised))), int(len(labelled))

    train_mae = _mae_vs_realised(df)
    if train_mae is not None:
        metrics["mae_vs_realised"], metrics["n_labelled"] = train_mae[0], float(train_mae[1])
    if val_df is not None and not val_df.empty:
        val_mae = _mae_vs_realised(val_df)
        if val_mae is not None:
            metrics["mae_vs_realised_val"], metrics["n_rows_val"] = (
                val_mae[0],
                float(val_mae[1]),
            )

    return ShiftTrainingResult(
        model=model,
        metrics=metrics,
        feature_importance={
            "team": w_team,
            "os": w_os,
            "indiv": (indiv_scale_top + indiv_scale_bottom) / 2.0,
        },
    )
