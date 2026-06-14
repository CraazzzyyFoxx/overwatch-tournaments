from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean

LOW_EVIDENCE_SHIFT_CAP = 1.5
STABLE_SHIFT_SCALE = 6.25
STABLE_SHRINKAGE_PRIOR = 1.5
STABLE_SHIFT_CLAMP = 3.0
TREND_SHIFT_CLAMP = 3.5

# The shift signal is the TEAM RESULT: how much the team over/under-performed in
# this tournament. On balancer-formed rosters (≈equal by rank) a team that wins
# more than expected means its players were under-rated → they deserve to move
# up; W/L deviation is therefore a direct, low-variance mis-rating signal, not
# "luck of the draw". Prod analysis confirms team W/L is by far the strongest
# predictor of realised division moves (Spearman ≈0.38), and individual impact
# adds ~0 on top of it. ``fit_raw_signal_weights`` can recalibrate; kept summing
# to 1 so ``STABLE_SHIFT_SCALE`` keeps its meaning.
RAW_SIGNAL_WEIGHTS: Mapping[str, float] = {
    "map_diff": 0.6,
    "placement_score": 0.4,
}


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class TournamentSignal:
    # Team-result components: normalised win/loss differential and team placement.
    map_diff: float
    placement_score: float
    recency_decay: float
    coverage_weight: float
    newcomer_weight: float
    match_count: int
    log_available: float


@dataclass(frozen=True)
class LinearAnalyticsMetrics:
    stable_shift: float
    trend_shift: float
    hybrid_shift: float
    confidence: float
    effective_evidence: float
    sample_tournaments: int
    sample_matches: int
    log_coverage: float


def _weight(signal: TournamentSignal) -> float:
    return signal.recency_decay * signal.coverage_weight * signal.newcomer_weight


def _raw_signal(
    signal: TournamentSignal, weights: Mapping[str, float] = RAW_SIGNAL_WEIGHTS
) -> float:
    return (
        weights.get("map_diff", 0.0) * signal.map_diff
        + weights.get("placement_score", 0.0) * signal.placement_score
    )


def _ema(values: Sequence[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _apply_low_evidence_cap(value: float, *, sample_tournaments: int, effective_evidence: float) -> float:
    if sample_tournaments <= 1 or effective_evidence < 1.0:
        return clamp(value, -LOW_EVIDENCE_SHIFT_CAP, LOW_EVIDENCE_SHIFT_CAP)
    return value


def fit_raw_signal_weights(
    components: Sequence[Sequence[float]],
    realised: Sequence[float],
    *,
    component_names: Sequence[str] = tuple(RAW_SIGNAL_WEIGHTS),
    min_samples: int = 30,
) -> dict[str, float]:
    """Refit the raw-signal weights against realised division moves.

    ``components`` is an ``(n, k)`` matrix whose columns align with
    ``component_names`` (defaults to :data:`RAW_SIGNAL_WEIGHTS`'s keys) and
    ``realised`` the per-row realised stable shift. Uses non-negative least
    squares and normalises the coefficients to sum to 1 so the fitted weights
    drop into :data:`RAW_SIGNAL_WEIGHTS` without rescaling ``STABLE_SHIFT_SCALE``.
    Falls back to the current defaults when there is too little data or the fit
    is degenerate. Offline helper — callers persist the result to config rather
    than hardcoding new literals.
    """
    import numpy as np
    from scipy.optimize import nnls

    names = tuple(component_names)
    matrix = np.asarray(components, dtype=float)
    target = np.asarray(realised, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] != len(names) or len(target) < min_samples:
        return dict(RAW_SIGNAL_WEIGHTS)

    coef, _ = nnls(matrix, target)
    total = float(coef.sum())
    if not np.isfinite(total) or total <= 1e-9:
        return dict(RAW_SIGNAL_WEIGHTS)

    weights = coef / total
    return {name: float(w) for name, w in zip(names, weights, strict=True)}


def score_history(
    signals: Sequence[TournamentSignal],
    *,
    openskill_shift: float | None = None,
    weights: Mapping[str, float] = RAW_SIGNAL_WEIGHTS,
    shift_scale: float = STABLE_SHIFT_SCALE,
) -> LinearAnalyticsMetrics:
    if not signals:
        return LinearAnalyticsMetrics(
            stable_shift=0.0,
            trend_shift=0.0,
            hybrid_shift=0.0,
            confidence=0.0,
            effective_evidence=0.0,
            sample_tournaments=0,
            sample_matches=0,
            log_coverage=0.0,
        )

    evidence_weights = [_weight(signal) for signal in signals]
    raws = [_raw_signal(signal, weights) for signal in signals]

    effective_evidence = sum(evidence_weights)
    sample_tournaments = len(signals)
    sample_matches = sum(max(signal.match_count, 0) for signal in signals)
    log_coverage = fmean(signal.log_available for signal in signals)

    weighted_raw = sum(
        weight * raw for weight, raw in zip(evidence_weights, raws, strict=True)
    )
    stable_shift = clamp(
        shift_scale * weighted_raw / (STABLE_SHRINKAGE_PRIOR + effective_evidence),
        -STABLE_SHIFT_CLAMP,
        STABLE_SHIFT_CLAMP,
    )
    stable_shift = _apply_low_evidence_cap(
        stable_shift,
        sample_tournaments=sample_tournaments,
        effective_evidence=effective_evidence,
    )

    if sample_tournaments >= 3:
        trend = _ema(raws, 2) - _ema(raws, 5)
        trend_shift = clamp(stable_shift + 0.35 * trend, -TREND_SHIFT_CLAMP, TREND_SHIFT_CLAMP)
    else:
        trend_shift = stable_shift
    trend_shift = _apply_low_evidence_cap(
        trend_shift,
        sample_tournaments=sample_tournaments,
        effective_evidence=effective_evidence,
    )

    if openskill_shift is None:
        hybrid_shift = stable_shift
    else:
        alpha_eff = 0.35 * min(1.0, sample_matches / 12.0)
        hybrid_shift = (1.0 - alpha_eff) * stable_shift + alpha_eff * openskill_shift
    hybrid_shift = _apply_low_evidence_cap(
        hybrid_shift,
        sample_tournaments=sample_tournaments,
        effective_evidence=effective_evidence,
    )

    confidence = clamp(
        0.55 * min(1.0, effective_evidence / 3.0)
        + 0.25 * min(1.0, sample_matches / 10.0)
        + 0.20 * log_coverage,
        0.0,
        1.0,
    )

    return LinearAnalyticsMetrics(
        stable_shift=stable_shift,
        trend_shift=trend_shift,
        hybrid_shift=hybrid_shift,
        confidence=confidence,
        effective_evidence=effective_evidence,
        sample_tournaments=sample_tournaments,
        sample_matches=sample_matches,
        log_coverage=log_coverage,
    )
