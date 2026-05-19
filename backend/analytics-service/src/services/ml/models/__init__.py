"""ML model implementations.

- :class:`base.MLModel` — Protocol common to every model kind.
- :mod:`performance_v2` — Performance Rating v2 (per-role LGBMRegressor).
- :mod:`shift_v2` — Player Shift v2 (OpenSkill + LGBM residual).
- :mod:`standings_v2` — Standings v2 (XGB pairwise + Monte Carlo).
- :mod:`match_quality` — post-hoc encounter quality + anomaly flags.
- :mod:`anomalies` — IsolationForest smurf / ruptures throw detectors.
"""
