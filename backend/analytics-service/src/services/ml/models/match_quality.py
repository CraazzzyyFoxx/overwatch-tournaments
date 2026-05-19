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


def _predictability(home_won: float | None, p_home: float | None) -> float:
    if home_won is None or p_home is None:
        return 50.0  # neutral when missing
    return float(np.clip(1 - abs(home_won - p_home), 0.0, 1.0)) * 100.0


def _skill_balance(home_mu: float | None, away_mu: float | None, sigma_pool: float = 300.0) -> float:
    if home_mu is None or away_mu is None or sigma_pool <= 0:
        return 50.0
    diff = abs(home_mu - away_mu)
    return float(np.clip(1 - diff / sigma_pool, 0.0, 1.0)) * 100.0


def compute_match_quality(
    encounters: pd.DataFrame,
    match_scores: pd.DataFrame,
    *,
    competitiveness_weight: float = 0.4,
    predictability_weight: float = 0.3,
    skill_balance_weight: float = 0.3,
) -> pd.DataFrame:
    """Return one row per encounter with the four sub-scores.

    Required columns in ``encounters``: ``encounter_id``, ``home_avg_mu``,
    ``away_avg_mu``, ``home_won`` (1/0/0.5/NaN), ``p_home_wins`` (optional).
    Required columns in ``match_scores``: ``encounter_id``, ``home_score``,
    ``away_score``.
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
        )
        weighted = (
            competitiveness_weight * comp
            + predictability_weight * pred
            + skill_balance_weight * skill
        )
        out.append(
            {
                "encounter_id": enc_id,
                "competitiveness": comp,
                "predictability": pred,
                "skill_balance": skill,
                "quality_score": float(np.clip(weighted, 0.0, 100.0)),
            }
        )
    return pd.DataFrame(out)
