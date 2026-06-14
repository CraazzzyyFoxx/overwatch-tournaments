"""Confidence calibration diagnostics for shift predictions.

The v2 models emit a ``confidence`` ∈ [0, 1] alongside every shift. Whether that
number is *meaningful* is an empirical question: a well-calibrated confidence
should rise as the realised error falls. This module turns
``(confidence, |error|)`` pairs collected over backtest folds into:

- a **reliability curve** — per-confidence-bin **hit rate**, where a prediction
  counts as a hit when ``|error| <= accuracy_tolerance`` (a genuine Bernoulli
  event, so the per-bin frequency is real — not a scale-dependent transform);
- an **Expected Calibration Error (ECE)** — the size-weighted gap between mean
  confidence and the empirical hit rate across bins (0 = perfectly calibrated);
- ``confidence_error_corr`` — Pearson correlation between confidence and the
  absolute error (should be **negative** when confidence is informative).

Because the "accuracy" is a real frequency of an explicit event rather than a
normalised error, the ECE here is not gameable by an arbitrary error scale (the
problem with the earlier ``1 - error/scale`` formulation). It is intentionally a
pure function so it can be unit-tested without a DB and reused both in the
rolling backtest and ad-hoc analysis.
"""

from __future__ import annotations

import typing

import numpy as np

__all__ = ("compute_calibration_report",)


def compute_calibration_report(
    confidences: typing.Iterable[float],
    errors: typing.Iterable[float],
    *,
    n_bins: int = 10,
    accuracy_tolerance: float = 0.5,
) -> dict[str, typing.Any]:
    """Return a reliability/ECE report for ``(confidence, |error|)`` pairs.

    A prediction is "accurate" when ``|error| <= accuracy_tolerance`` (half a
    division by default). Bins span ``[0, 1]`` confidence in ``n_bins`` equal
    slices; ``ece`` is the size-weighted ``|mean_confidence - hit_rate|`` gap.
    """
    conf = np.asarray(list(confidences), dtype=float)
    err = np.asarray(list(errors), dtype=float)
    finite = np.isfinite(conf) & np.isfinite(err)
    conf, err = conf[finite], err[finite]
    n = int(conf.size)
    if n == 0:
        return {
            "n": 0,
            "ece": None,
            "accuracy_tolerance": float(accuracy_tolerance),
            "accuracy_rate": None,
            "confidence_error_corr": None,
            "bins": [],
        }

    hits = (err <= accuracy_tolerance).astype(float)

    edges = np.linspace(0.0, 1.0, n_bins + 1)
    bins: list[dict[str, typing.Any]] = []
    ece = 0.0
    for i in range(n_bins):
        lo, hi = float(edges[i]), float(edges[i + 1])
        # Include the right edge only in the final bin so 1.0 lands somewhere.
        selected = (conf >= lo) & (conf <= hi) if i == n_bins - 1 else (conf >= lo) & (conf < hi)
        count = int(selected.sum())
        if count == 0:
            bins.append(
                {
                    "bin_lo": lo,
                    "bin_hi": hi,
                    "n": 0,
                    "mean_confidence": None,
                    "hit_rate": None,
                    "mean_error": None,
                }
            )
            continue
        mean_conf = float(conf[selected].mean())
        hit_rate = float(hits[selected].mean())
        mean_err = float(err[selected].mean())
        ece += (count / n) * abs(mean_conf - hit_rate)
        bins.append(
            {
                "bin_lo": lo,
                "bin_hi": hi,
                "n": count,
                "mean_confidence": mean_conf,
                "hit_rate": hit_rate,
                "mean_error": mean_err,
            }
        )

    if np.std(conf) < 1e-12 or np.std(err) < 1e-12:
        corr: float | None = None
    else:
        corr = float(np.corrcoef(conf, err)[0, 1])

    return {
        "n": n,
        "ece": float(ece),
        "accuracy_tolerance": float(accuracy_tolerance),
        "accuracy_rate": float(hits.mean()),
        "confidence_error_corr": corr,
        "bins": bins,
    }
