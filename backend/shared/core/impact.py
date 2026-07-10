"""Shared constants of the MVP impact formula (spec 2026-07-10).

Weights apply to winsorized z-scores of per-10-minute rates. Keys are
``LogStatsName`` member NAMES (the same strings SQLAlchemy persists).
Bump ``FORMULA_VERSION`` whenever weights or baseline semantics change —
baselines are versioned by it and old scores stay on the old version
until an explicit backfill.
"""

from typing import Final

FORMULA_VERSION: Final = "impact_v1"

IMPACT_WEIGHTS: Final[dict[str, float]] = {
    "Eliminations": 1.3,
    "FinalBlows": 0.4,
    "Deaths": -1.3,
    "HeroDamageDealt": 0.35,
    "HealingDealt": 0.35,
    "DamageBlocked": 0.25,
    "OffensiveAssists": 0.45,
    "DefensiveAssists": 0.45,
    "UltimatesUsed": 0.1,
    "Multikills": 0.45,
    "SoloKills": 0.35,
    "ObjectiveKills": 0.3,
    "EnvironmentalKills": 0.2,
    "FirstPicks": 0.55,
    "FirstDeaths": -0.45,
    "UltimateKills": 0.5,
    "SupportKills": 0.3,
}

#: Stats derived from kill_feed — zeroed (not penalized) when a match has no feed.
EVENT_STATS: Final = ("FirstPicks", "FirstDeaths", "UltimateKills", "SupportKills")

WINSOR_LIMIT: Final = 3.0
#: Badge = top-1 OverperformanceScore in the match AND score >= threshold.
BADGE_THRESHOLD: Final = 2.0
#: Below this playtime a player's impact score is 0.
MIN_SECONDS: Final = 60.0
RANK_BUCKETS: Final = 3
#: Player-match rows entering baseline aggregation need >= this playtime.
BASELINE_MIN_MINUTES: Final = 3.0
