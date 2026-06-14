"""Machine-learning v2 pipeline for analytics-service.

Subpackages:

- ``features`` — SQL → DataFrame extractors (round/match/encounter/tournament
  granularity) + role-specific KPI lists + opponent-strength snapshots.
- ``models`` — Performance v2 / Shift v2 / Standings v2 / Match-quality
  estimators (added incrementally per phase).
- ``training`` — orchestrator + time-series splits + artifact registry.
- ``inference`` — runner that loads active artifacts and writes predictions.
- ``explain`` — SHAP attribution utilities.
- ``metrics`` — regression / classification / ranking metric helpers.
"""

FEATURE_VERSION = "v1.0"
