"""Feature engineering layer for the v2 ML pipeline.

Public entry points:

- :func:`extractors.extract_match_features` — one row per ``(player, match)``,
  pivoted from ``matches.statistics`` with per-10-min rate columns.
- :func:`extractors.extract_tournament_features` — roll-up of match features
  to ``(player, tournament)`` weighted by ``hero_time_played``.
- :func:`extractors.extract_encounter_features` — pairwise team matchup
  vector per ``Encounter`` (for the win-probability classifier).
- :func:`opponent_strength.snapshot_pre_encounter_mu` — frozen OpenSkill mu
  per ``(player, encounter)`` evaluated before the encounter starts.
- :data:`role_kpis.ROLE_KPIS` — role-specific feature column lists.
"""

from .extractors import (
    STAT_COLUMNS,
    extract_encounter_features,
    extract_match_features,
    extract_tournament_features,
)
from .role_kpis import ROLE_KPIS, COARSE_FEATURES

__all__ = (
    "ROLE_KPIS",
    "COARSE_FEATURES",
    "STAT_COLUMNS",
    "extract_encounter_features",
    "extract_match_features",
    "extract_tournament_features",
)
