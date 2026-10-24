"""Role-specific KPI columns + coarse-fallback feature list.

The Performance v2 model trains one LightGBM regressor per role using the
column list from :data:`ROLE_KPIS`. When per-match logs are missing
(``log_coverage = 0``), inference falls back to the much smaller
:data:`COARSE_FEATURES` list — rank / opponent-strength only.

Column names match the per-10-min rate columns produced by
:func:`shared.disciplines.overwatch.analytics.features.extractors.extract_match_features` and the
aggregated columns produced by
:func:`shared.disciplines.overwatch.analytics.features.extractors.extract_tournament_features`.
"""

from __future__ import annotations

#: The role axes of the Overwatch analytics frames, in column order (``tank_mu``, ``damage_mu``, ``support_mu``, ...).
ROLES: tuple[str, ...] = ("tank", "damage", "support")

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

# Coarse fallback features used when no usable player facts are available.
# Rank / opponent strength only — no per-stat detail, and no match outcome
# (``won``, scores): the Performance target is ``won - P(win)``, so those columns leak the label.
COARSE_FEATURES: list[str] = [
    "mu_gap",
    "opp_avg_mu",
    "team_avg_mu",
    "is_home",
    "rank",
    "is_newcomer",
]


def features_for_role(role: str) -> list[str]:
    """Return the trained KPI column list for an Overwatch role.

    The caller resolves the role against the discipline's rated dimension first; a role this module has no trained
    feature list for is rejected, never served another role's model inputs.
    """
    try:
        return ROLE_KPIS[role.lower()]
    except KeyError:
        raise ValueError(f"no Overwatch trained-feature list for role {role!r}") from None
