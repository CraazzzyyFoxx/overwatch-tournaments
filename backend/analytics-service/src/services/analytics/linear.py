from __future__ import annotations

from dataclasses import dataclass
from math import copysign
from statistics import fmean
from typing import Sequence

LOW_EVIDENCE_SHIFT_CAP = 1.5
STABLE_SHIFT_SCALE = 6.25
STABLE_SHRINKAGE_PRIOR = 1.5
STABLE_SHIFT_CLAMP = 3.0
TREND_SHIFT_CLAMP = 3.5


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


@dataclass(frozen=True)
class TournamentSignal:
    map_diff: float
    placement_score: float
    log_residual: float
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


def _raw_signal(signal: TournamentSignal) -> float:
    return 0.50 * signal.map_diff + 0.35 * signal.placement_score + 0.15 * signal.log_residual


def _ema(values: Sequence[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def _has_signal_disagreement(signal: TournamentSignal) -> bool:
    non_zero = [
        int(copysign(1, value))
        for value in (signal.map_diff, signal.placement_score, signal.log_residual)
        if abs(value) > 1e-9
    ]
    return len(set(non_zero)) > 1


def _apply_low_evidence_cap(value: float, *, sample_tournaments: int, effective_evidence: float) -> float:
    if sample_tournaments <= 1 or effective_evidence < 1.0:
        return clamp(value, -LOW_EVIDENCE_SHIFT_CAP, LOW_EVIDENCE_SHIFT_CAP)
    return value


def score_history(
    signals: Sequence[TournamentSignal],
    *,
    openskill_shift: float | None = None,
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

    weights = [_weight(signal) for signal in signals]
    raws = [_raw_signal(signal) for signal in signals]

    effective_evidence = sum(weights)
    sample_tournaments = len(signals)
    sample_matches = sum(max(signal.match_count, 0) for signal in signals)
    log_coverage = fmean(signal.log_available for signal in signals)

    weighted_raw = sum(weight * raw for weight, raw in zip(weights, raws, strict=True))
    stable_shift = clamp(
        STABLE_SHIFT_SCALE * weighted_raw / (STABLE_SHRINKAGE_PRIOR + effective_evidence),
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
    if _has_signal_disagreement(signals[-1]):
        confidence *= 0.8

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
