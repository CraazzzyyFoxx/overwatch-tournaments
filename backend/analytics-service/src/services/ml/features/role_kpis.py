"""Role-specific KPI columns + coarse-fallback feature list.

The Performance v2 model trains one LightGBM regressor per role using the
column list from :data:`ROLE_KPIS`. When per-match logs are missing
(``log_coverage = 0``), inference falls back to the much smaller
:data:`COARSE_FEATURES` list — score / standings / opponent-strength only.

Column names match the per-10-min rate columns produced by
:func:`src.services.ml.features.extractors.extract_match_features` and the
aggregated columns produced by
:func:`src.services.ml.features.extractors.extract_tournament_features`.
"""

from __future__ import annotations

# Per-role feature lists (sub-roles map to these top-level roles).
# Keys match shared.core.enums.PlayerRole string values.
ROLE_KPIS: dict[str, list[str]] = {
    "tank": [
        "damage_blocked_p10",
        "objective_kills_p10",
        "deaths_p10",
        "ult_economy",
        "damage_taken_p10",
        "all_damage_p10",
        "mu_gap",
        "opp_avg_mu",
        "team_avg_mu",
    ],
    "damage": [
        "final_blows_p10",
        "hero_damage_p10",
        "weapon_accuracy",
        "critical_hit_accuracy",
        "solo_kills_p10",
        "eliminations_p10",
        "deaths_p10",
        "ult_economy",
        "mu_gap",
        "opp_avg_mu",
        "team_avg_mu",
    ],
    "support": [
        "healing_p10",
        "defensive_assists_p10",
        "offensive_assists_p10",
        "deaths_p10",
        "self_healing_p10",
        "ult_economy",
        "mu_gap",
        "opp_avg_mu",
        "team_avg_mu",
    ],
}

# Coarse fallback features used when no MatchStatistics are available.
# Score / standings / opponent strength only — no per-stat detail.
COARSE_FEATURES: list[str] = [
    "won",
    "home_score",
    "away_score",
    "score_delta",
    "mu_gap",
    "opp_avg_mu",
    "team_avg_mu",
    "is_home",
    "rank",
    "is_newcomer",
]


def features_for_role(role: str) -> list[str]:
    """Return the KPI column list for a role, falling back to damage list."""
    return ROLE_KPIS.get(role.lower(), ROLE_KPIS["damage"])
