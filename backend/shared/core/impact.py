"""Shared constants of the MVP impact formula (``impact_v2``).

The formula and its storage are specified in ``docs/superpowers/specs/2026-10-31-mvp-impact-v2-design.md``. Feature
keys are ``LogStatsName`` member NAMES. Bump ``FORMULA_VERSION`` whenever weights or baseline semantics change:
baselines are versioned by it and stored scores keep the version they were computed with until a full backfill.
The fitted weights live in ``shared.core.impact_weights`` (written by ``stats-service/fit_impact_weights.py``).
"""

from typing import Final

from shared.core.enums import HeroClass, LogStatsName

FORMULA_VERSION: Final = "impact_v2"

#: The rated roles a stint is scored in: the hero classes (``flex`` is a roster slot, never a hero class).
IMPACT_ROLES: Final = tuple(hero_class.name for hero_class in HeroClass if hero_class is not HeroClass.flex)

IMPACT_FEATURES: Final = (
    "Eliminations",
    "FinalBlows",
    "Deaths",
    "HeroDamageDealt",
    "HealingDealt",
    "DamageBlocked",
    "DamageTaken",
    "BarrierDamageDealt",
    "OffensiveAssists",
    "DefensiveAssists",
    "UltimatesEarned",
    "UltimatesUsed",
    "Multikills",
    "SoloKills",
    "ObjectiveKills",
    "EnvironmentalKills",
    "FirstPicks",
    "FirstDeaths",
    "UltimateKills",
    "SupportKills",
)

#: Features counted from the kill feed (attributed to the killer's hero, or the victim's for ``FirstDeaths``). A match
#: without a kill feed scores them as 0 and they never enter a baseline from such a match.
EVENT_STATS: Final = ("FirstPicks", "FirstDeaths", "UltimateKills", "SupportKills")

#: The ridge prior of the weight fit: the ``impact_v1`` weights, 0 for the features v1 did not score.
PRIOR_WEIGHTS: Final[dict[str, float]] = {
    "Eliminations": 1.3,
    "FinalBlows": 0.4,
    "Deaths": -1.3,
    "HeroDamageDealt": 0.35,
    "HealingDealt": 0.35,
    "DamageBlocked": 0.25,
    "DamageTaken": 0.0,
    "BarrierDamageDealt": 0.0,
    "OffensiveAssists": 0.45,
    "DefensiveAssists": 0.45,
    "UltimatesEarned": 0.0,
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

#: Feature NAME -> the stat its per-map contribution is stored under.
CONTRIBUTION_STATS: Final[dict[str, LogStatsName]] = {
    feature: LogStatsName[f"Contrib{feature}"] for feature in IMPACT_FEATURES
}

WINSOR_LIMIT: Final = 3.0
#: A player with fewer classed seconds in a segment is not scored there (no impact facts at all).
MIN_SECONDS: Final = 60.0
#: Stints entering baseline aggregation need at least this playtime.
BASELINE_MIN_MINUTES: Final = 3.0
#: A hero gets its own baseline for a feature once it has this many qualifying stints; below it, its role's.
HERO_BASELINE_MIN_ROWS: Final = 30
#: Quality is shrunk towards 0 by ``minutes / (minutes + SHRINK_MINUTES)``.
SHRINK_MINUTES: Final = 3.0
RANK_QUINTILES: Final = 5
#: Fewer ranked players than this for a role in an owner: no rank quintile, so no overperformance.
MIN_RANK_POPULATION: Final = 5
BASELINE_WINDOW_DAYS: Final = 365
#: Baselines read at most this many of the window's most recent maps, so a recompute never scans all history.
BASELINE_MAX_MATCHES: Final = 5000
#: The badge threshold is this percentile of the baseline player-maps' overperformance.
BADGE_PERCENTILE: Final = 95.0
