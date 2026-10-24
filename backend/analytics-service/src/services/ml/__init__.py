"""Machine-learning v2 pipeline for analytics-service.

Subpackages:

- ``features`` — feature-frame loading, the feature cache and opponent-strength
  snapshots.
- ``models`` — artifact storage and anomaly-threshold tuning.
- ``training`` — orchestrator + time-series splits + artifact registry.
- ``inference`` — runner that loads active artifacts and writes predictions.
"""

# Bump on any change to feature-frame semantics so the file/disk feature cache
# is invalidated.
FEATURE_VERSION = "v1.6"
