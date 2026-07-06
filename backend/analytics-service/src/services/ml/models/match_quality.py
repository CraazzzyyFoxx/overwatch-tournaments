"""Match Quality v1 — competitiveness / predictability / skill-balance scores.

Unlike the other v2 estimators, Match Quality is *deterministic*: no trained
booster is involved. Anomaly detection lives in :mod:`anomalies` and is
loaded on demand.

Inputs per ``Encounter``:

- ``home_score``, ``away_score`` per match (from ``matches.match``)
- pre-encounter team mu snapshot (from ``opponent_strength``)
- realised winner + the Standings-v2 ``p_home_wins`` if available

Outputs per ``Encounter`` (0-100 each, plus weighted ``quality_score``):

- ``competitiveness`` — Shannon entropy of round-score deltas + lead changes
  + final-score-gap component.
- ``predictability``  — ``1 - |actual - p_home_wins|`` × 100.
- ``skill_balance``   — ``1 - |home_avg_mu - away_avg_mu| / sigma_pool`` × 100.
- ``quality_score``   — weighted sum (40/30/30 default).
"""

from __future__ import annotations

import math
import typing
from dataclasses import dataclass

import numpy as np
import pandas as pd

__all__ = (
    "MatchQualityComponents",
    "compute_match_quality",
)

# Default component weights for the composite quality score. Named (not inline
# literals) so they can be overridden per call / from config.
COMPETITIVENESS_WEIGHT = 0.4
PREDICTABILITY_WEIGHT = 0.3
SKILL_BALANCE_WEIGHT = 0.3

# Fallback skill-balance scale (OpenSkill sigma) when no per-tournament mu gap
# distribution is available to derive one from.
DEFAULT_SIGMA_POOL = 300.0


@dataclass
class MatchQualityComponents:
    encounter_id: int
    competitiveness: float
    predictability: float
    skill_balance: float
    quality_score: float


def _shannon_entropy(values: typing.Sequence[float]) -> float:
    """Normalised Shannon entropy ∈ [0, 1] of the value distribution."""
    if not values:
        return 0.0
    arr = np.asarray(values, dtype=float)
    arr = np.abs(arr)
    total = arr.sum()
    if total <= 0:
        return 0.0
    p = arr / total
    p = p[p > 0]
    h = float(-(p * np.log(p)).sum())
    h_max = math.log(len(p)) if len(p) > 1 else 1.0
    return float(np.clip(h / h_max, 0.0, 1.0))


def _competitiveness(scores: list[tuple[int, int]]) -> float:
    """Map list of ``(home_score, away_score)`` → 0-100 competitiveness."""
    if not scores:
        return 0.0
    deltas = [h - a for h, a in scores]
    entropy = _shannon_entropy(deltas) * 40.0

    # Lead changes count.
    leader_history = [(1 if h > a else -1 if a > h else 0) for h, a in scores]
    lead_changes = sum(
        1
        for prev, curr in zip(leader_history[:-1], leader_history[1:], strict=False)
        if prev != 0 and curr != 0 and prev != curr
    )
    lead_score = float(np.clip(lead_changes / max(len(scores) - 1, 1), 0.0, 1.0)) * 30.0

    final_h, final_a = scores[-1]
    max_score = max(abs(final_h), abs(final_a), 1)
    final_score = (1 - abs(final_h - final_a) / max_score) * 30.0
    return float(np.clip(entropy + lead_score + final_score, 0.0, 100.0))


def _is_missing(value: float | None) -> bool:
    """True for ``None`` *or* a non-finite (NaN/inf) value.

    A pandas/numpy ``NaN`` is **not** ``None`` and slips past a bare
    ``is None`` check. Left unguarded it flows into ``np.clip`` (which never
    sanitises NaN) and leaks a NaN sub-score, which 500s the read endpoint —
    Starlette serialises responses with ``json.dumps(..., allow_nan=False)``.
    """
    return value is None or not math.isfinite(float(value))


def _predictability(home_won: float | None, p_home: float | None) -> float:
    if _is_missing(home_won) or _is_missing(p_home):
        return 50.0  # neutral when missing
    return float(np.clip(1 - abs(home_won - p_home), 0.0, 1.0)) * 100.0


def _skill_balance(home_mu: float | None, away_mu: float | None, sigma_pool: float = DEFAULT_SIGMA_POOL) -> float:
    if _is_missing(home_mu) or _is_missing(away_mu) or sigma_pool <= 0:
        return 50.0
    diff = abs(home_mu - away_mu)
    return float(np.clip(1 - diff / sigma_pool, 0.0, 1.0)) * 100.0


def _derive_sigma_pool(gaps: typing.Sequence[float]) -> float:
    """Skill-balance scale from the field's own mu-gap distribution.

    A hardcoded 300 makes every encounter with a >300 mu gap collapse to a
    skill_balance of 0, regardless of how the field is actually spread. Using
    the 90th percentile of the observed ``|home_mu - away_mu|`` means the most
    lopsided matches of *this* tournament anchor 0 and even matches anchor 100.
    The scale is per-tournament, so ``skill_balance`` is a *within-field relative*
    measure (a 0 in two tournaments need not be the same absolute mu gap), not an
    absolute one. Falls back to :data:`DEFAULT_SIGMA_POOL` when there are no gaps.
    """
    cleaned = [abs(float(gap)) for gap in gaps if gap is not None and np.isfinite(gap)]
    if not cleaned:
        return DEFAULT_SIGMA_POOL
    return max(float(np.percentile(cleaned, 90)), 1.0)


def compute_match_quality(
    encounters: pd.DataFrame,
    match_scores: pd.DataFrame,
    *,
    competitiveness_weight: float = COMPETITIVENESS_WEIGHT,
    predictability_weight: float = PREDICTABILITY_WEIGHT,
    skill_balance_weight: float = SKILL_BALANCE_WEIGHT,
    sigma_pool: float | None = None,
) -> pd.DataFrame:
    """Return one row per encounter with the four sub-scores.

    Required columns in ``encounters``: ``encounter_id``, ``home_avg_mu``,
    ``away_avg_mu``, ``home_won`` (1/0/0.5/NaN), ``p_home_wins`` (optional).
    Required columns in ``match_scores``: ``encounter_id``, ``home_score``,
    ``away_score``.

    ``sigma_pool`` controls the skill-balance scale; when omitted it is derived
    from this field's own ``|home_avg_mu - away_avg_mu|`` distribution instead of
    a fixed 300 (see :func:`_derive_sigma_pool`).
    """
    if encounters.empty:
        return pd.DataFrame(
            columns=[
                "encounter_id",
                "competitiveness",
                "predictability",
                "skill_balance",
                "quality_score",
            ]
        )

    # Enforce the one-row-per-encounter contract. Upstream LEFT-join merges in
    # ``build_standings_training_frame`` can fan a single encounter into several
    # rows; left unguarded those propagate into the writer's INSERT and trip
    # ``uq_analytics_match_quality (encounter_id, algorithm_id)`` (a delete
    # before insert can't help — the duplicate is within one INSERT). Dropping
    # here also keeps the derived ``sigma_pool`` from double-counting mu gaps.
    encounters = encounters.drop_duplicates(subset="encounter_id", keep="first")

    if sigma_pool is None:
        gaps = [
            float(home) - float(away)
            for home, away in zip(
                encounters.get("home_avg_mu", pd.Series(dtype=float)),
                encounters.get("away_avg_mu", pd.Series(dtype=float)),
                strict=False,
            )
            if home is not None and away is not None and not pd.isna(home) and not pd.isna(away)
        ]
        sigma_pool = _derive_sigma_pool(gaps)

    scores_by_enc: dict[int, list[tuple[int, int]]] = {}
    if not match_scores.empty:
        for row in match_scores.itertuples(index=False):
            scores_by_enc.setdefault(int(row.encounter_id), []).append(
                (int(row.home_score or 0), int(row.away_score or 0))
            )

    out: list[dict[str, typing.Any]] = []
    for row in encounters.itertuples(index=False):
        enc_id = int(row.encounter_id)
        comp = _competitiveness(scores_by_enc.get(enc_id, []))
        pred = _predictability(
            getattr(row, "home_won", None),
            getattr(row, "p_home_wins", None),
        )
        skill = _skill_balance(
            getattr(row, "home_avg_mu", None),
            getattr(row, "away_avg_mu", None),
            sigma_pool=sigma_pool,
        )
        weighted = competitiveness_weight * comp + predictability_weight * pred + skill_balance_weight * skill
        out.append(
            {
                "encounter_id": enc_id,
                "competitiveness": comp,
                "predictability": pred,
                "skill_balance": skill,
                "quality_score": float(np.clip(weighted, 0.0, 100.0)),
            }
        )
    result = pd.DataFrame(out)
    # Defence in depth: never emit a non-finite sub-score. The component
    # helpers already return neutral values when inputs are missing, but a
    # single NaN here 500s the read endpoint (Starlette uses allow_nan=False),
    # so we scrub inf→NaN→neutral as a last line before persistence.
    neutral = {
        "competitiveness": 0.0,
        "predictability": 50.0,
        "skill_balance": 50.0,
        "quality_score": 30.0,
    }
    result[list(neutral)] = result[list(neutral)].replace([np.inf, -np.inf], np.nan).fillna(neutral)
    return result
