"""Linear team-result scoring. No session."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import fmean

LOW_EVIDENCE_SHIFT_CAP = 1.5
STABLE_SHIFT_SCALE = 6.25
STABLE_SHRINKAGE_PRIOR = 1.5
STABLE_SHIFT_CLAMP = 3.0
TREND_SHIFT_CLAMP = 3.5
# A tournament's evidence grows with its maps as n/(n + MAP_WEIGHT_PRIOR): one map is barely a sample, twenty are.
MAP_WEIGHT_PRIOR = 4
# A raw-signal sd below this is float rounding of a constant signal, not noise.
_MIN_NOISE_SD = 1e-9

# The shift signal is the TEAM RESULT: how much the team over/under-performed in
# this tournament. On balancer-formed rosters (≈equal by rank) a team that wins
# more than expected means its players were under-rated → they deserve to move
# up; W/L deviation is therefore a direct, low-variance mis-rating signal, not
# "luck of the draw". Team W/L is by far the strongest predictor of realised
# division moves, and individual impact adds ~0 on top of it.
# Kept summing to 1 so ``STABLE_SHIFT_SCALE`` keeps its meaning.
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
    #: Maps played (wins + losses); the match count when the tournament recorded no maps.
    maps: int
    match_count: int
    log_available: float


@dataclass(frozen=True)
class LinearAnalyticsMetrics:
    stable_shift: float
    trend_shift: float
    #: Posterior sd of ``stable_shift`` in divisions; None when the signal noise is unknown.
    shift_sd: float | None
    effective_evidence: float
    sample_tournaments: int
    sample_matches: int
    log_coverage: float


def map_weight(maps: int) -> float:
    """Evidence of one tournament's sample: n/(n + MAP_WEIGHT_PRIOR) for n maps; no maps carry none."""
    return maps / (maps + MAP_WEIGHT_PRIOR) if maps > 0 else 0.0


def _weight(signal: TournamentSignal) -> float:
    return signal.recency_decay * signal.coverage_weight * map_weight(signal.maps)


def _raw_signal(signal: TournamentSignal, weights: Mapping[str, float] = RAW_SIGNAL_WEIGHTS) -> float:
    return weights.get("map_diff", 0.0) * signal.map_diff + weights.get("placement_score", 0.0) * signal.placement_score


def _ema(values: Sequence[float], period: int) -> float:
    if not values:
        return 0.0
    alpha = 2.0 / (period + 1.0)
    result = values[0]
    for value in values[1:]:
        result = alpha * value + (1.0 - alpha) * result
    return result


def raw_signal_sd(
    signals: Sequence[TournamentSignal],
    weights: Mapping[str, float] = RAW_SIGNAL_WEIGHTS,
) -> float | None:
    """Noise sd ``s`` of one tournament's raw signal: its map-weighted sd across ``signals``.

    None when it is undefined (no maps anywhere) or zero (every signal equal, up to float rounding): no posterior sd
    follows from it.
    """
    map_weights = [map_weight(signal.maps) for signal in signals]
    total = sum(map_weights)
    if total <= 0:
        return None
    raws = [_raw_signal(signal, weights) for signal in signals]
    mean = sum(w * raw for w, raw in zip(map_weights, raws, strict=True)) / total
    variance = sum(w * (raw - mean) ** 2 for w, raw in zip(map_weights, raws, strict=True)) / total
    noise_sd = math.sqrt(variance)
    return noise_sd if noise_sd > _MIN_NOISE_SD else None


def _apply_low_evidence_cap(value: float, *, sample_tournaments: int, effective_evidence: float) -> float:
    if sample_tournaments <= 1 or effective_evidence < 1.0:
        return clamp(value, -LOW_EVIDENCE_SHIFT_CAP, LOW_EVIDENCE_SHIFT_CAP)
    return value


def score_history(
    signals: Sequence[TournamentSignal],
    *,
    noise_sd: float | None,
    weights: Mapping[str, float] = RAW_SIGNAL_WEIGHTS,
    shift_scale: float = STABLE_SHIFT_SCALE,
) -> LinearAnalyticsMetrics:
    """Score one player's history; ``noise_sd`` is the raw-signal noise ``s`` (:func:`raw_signal_sd`).

    ``shift_sd`` is the posterior sd of the shrunk mean: shift_scale · s / sqrt(STABLE_SHRINKAGE_PRIOR + evidence).
    """
    if not signals:
        return LinearAnalyticsMetrics(
            stable_shift=0.0,
            trend_shift=0.0,
            shift_sd=None,
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

    weighted_raw = sum(weight * raw for weight, raw in zip(evidence_weights, raws, strict=True))
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

    shift_sd = (
        shift_scale * noise_sd / math.sqrt(STABLE_SHRINKAGE_PRIOR + effective_evidence)
        if noise_sd is not None
        else None
    )

    return LinearAnalyticsMetrics(
        stable_shift=stable_shift,
        trend_shift=trend_shift,
        shift_sd=shift_sd,
        effective_evidence=effective_evidence,
        sample_tournaments=sample_tournaments,
        sample_matches=sample_matches,
        log_coverage=log_coverage,
    )
