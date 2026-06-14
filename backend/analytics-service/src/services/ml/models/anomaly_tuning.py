"""Threshold tuning for anomaly detectors from reviewer labels.

The detectors in :mod:`anomalies` emit signals with hand-set cut-offs
(``impact_threshold``, ``z_threshold``, ``pelt_penalty`` …). Once admins label
those signals via ``analytics.anomaly_feedback`` (confirmed = true positive,
dismissed = false positive), this module turns the labels into a
precision/recall curve and picks the score cut-off that reaches a target
precision with the most recall — so the thresholds stop being magic numbers.

Pure functions (no DB) so they unit-test cleanly; the caller fetches
``(score, is_true_positive)`` pairs per anomaly ``kind`` and feeds them in.
"""

from __future__ import annotations

import typing

import numpy as np

__all__ = ("precision_recall_curve", "tune_threshold")


def precision_recall_curve(
    scores: typing.Sequence[float], labels: typing.Sequence[bool]
) -> list[dict[str, float]]:
    """Return precision/recall at each candidate ``score >= threshold`` cut-off.

    ``labels[i]`` is ``True`` when the flagged player was confirmed a true
    positive. Each point: ``threshold``, ``precision``, ``recall``, ``flagged``
    (count at/above the cut-off) and ``tp`` (confirmed among them).
    """
    score_arr = np.asarray(scores, dtype=float)
    label_arr = np.asarray(labels, dtype=bool)
    if score_arr.size == 0:
        return []

    total_positives = int(label_arr.sum())
    out: list[dict[str, float]] = []
    for threshold in np.unique(score_arr):
        flagged = score_arr >= threshold
        n_flagged = int(flagged.sum())
        tp = int((flagged & label_arr).sum())
        precision = tp / n_flagged if n_flagged else 0.0
        recall = tp / total_positives if total_positives else 0.0
        out.append(
            {
                "threshold": float(threshold),
                "precision": float(precision),
                "recall": float(recall),
                "flagged": float(n_flagged),
                "tp": float(tp),
            }
        )
    return out


def tune_threshold(
    scores: typing.Sequence[float],
    labels: typing.Sequence[bool],
    *,
    target_precision: float = 0.8,
) -> dict[str, float] | None:
    """Pick the cut-off that meets ``target_precision`` with the most recall.

    Returns the chosen curve point (``threshold``/``precision``/``recall``/…) or
    ``None`` when no cut-off reaches the target (e.g. too few confirmed labels).
    Ties on recall break toward the lower threshold (more inclusive).
    """
    qualifying = [
        point
        for point in precision_recall_curve(scores, labels)
        if point["flagged"] > 0 and point["precision"] >= target_precision
    ]
    if not qualifying:
        return None
    return max(qualifying, key=lambda point: (point["recall"], -point["threshold"]))
