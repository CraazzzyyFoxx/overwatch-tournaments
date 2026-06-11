from __future__ import annotations

import typing

from src.config_presets import ConfigPresets
from src.core.config import AlgorithmConfig
from src.domain.balancer.public_contract import (
    drop_legacy_public_config_keys,
    normalize_persisted_config_payload,
    serialize_algorithm_config,
)
from src.domain.balancer.public_contract import (
    normalize_config_overrides as normalize_external_config_overrides,
)

CONFIG_LIMITS: dict[str, dict[str, int | float]] = {
    "population_size": {"min": 10, "max": 1000},
    "generation_count": {"min": 10, "max": 5000},
    "mutation_rate": {"min": 0.0, "max": 1.0},
    "mutation_strength": {"min": 1, "max": 10},
    "average_mmr_balance_weight": {"min": 0.0, "max": 10000.0},
    "team_total_balance_weight": {"min": 0.0, "max": 10000.0},
    "role_discomfort_weight": {"min": 0.0, "max": 10000.0},
    "max_role_discomfort_weight": {"min": 0.0, "max": 10000.0},
    "role_line_balance_weight": {"min": 0.0, "max": 10000.0},
    "intra_team_std_weight": {"min": 0.0, "max": 10000.0},
    "internal_role_spread_weight": {"min": 0.0, "max": 10000.0},
    "sub_role_collision_weight": {"min": 0.0, "max": 10000.0},
    "team_max_pain_weight": {"min": 0.0, "max": 10000.0},
    "max_team_gap_weight": {"min": 0.0, "max": 10000.0},
    "tank_impact_weight": {"min": 0.0, "max": 10000.0},
    "dps_impact_weight": {"min": 0.0, "max": 10000.0},
    "support_impact_weight": {"min": 0.0, "max": 10000.0},
    "tank_gap_weight": {"min": 0.0, "max": 10000.0},
    "tank_std_weight": {"min": 0.0, "max": 10000.0},
    "effective_total_std_weight": {"min": 0.0, "max": 10000.0},
    "convergence_patience": {"min": 0, "max": 5000},
    "convergence_epsilon": {"min": 0.0, "max": 1.0},
    "mutation_rate_min": {"min": 0.0, "max": 1.0},
    "mutation_rate_max": {"min": 0.0, "max": 1.0},
    "island_count": {"min": 1, "max": 64},
    "polish_max_passes": {"min": 0, "max": 1000},
    "greedy_seed_count": {"min": 0, "max": 1000},
    "stagnation_kick_patience": {"min": 0, "max": 5000},
    "crossover_rate": {"min": 0.0, "max": 1.0},
    "time_limit_ms": {"min": 100, "max": 600000},
    "max_result_variants": {"min": 1, "max": 200},
}

EDITABLE_CONFIG_FIELD_KEYS = {
    "role_mask",
    "population_size",
    "generation_count",
    "mutation_rate",
    "mutation_strength",
    "average_mmr_balance_weight",
    "team_total_balance_weight",
    "max_team_gap_weight",
    "role_discomfort_weight",
    "max_role_discomfort_weight",
    "role_line_balance_weight",
    "intra_team_std_weight",
    "internal_role_spread_weight",
    "sub_role_collision_weight",
    "team_max_pain_weight",
    "tank_impact_weight",
    "dps_impact_weight",
    "support_impact_weight",
    "tank_gap_weight",
    "tank_std_weight",
    "effective_total_std_weight",
    "use_captains",
    "convergence_patience",
    "convergence_epsilon",
    "mutation_rate_min",
    "mutation_rate_max",
    "island_count",
    "polish_max_passes",
    "greedy_seed_count",
    "stagnation_kick_patience",
    "crossover_rate",
    "time_limit_ms",
    "max_result_variants",
}

SYSTEM_CONFIG_FIELD_KEYS = {
    "workspace_id",
    "tournament_id",
    "division_grid",
    "division_scope",
}

CONFIG_FIELD_DEFINITIONS: list[dict[str, typing.Any]] = [
    {
        "key": "role_mask",
        "label": "Role mask",
        "description": "Required player count per team role. Default Overwatch format is 1 Tank, 2 Damage, 2 Support.",
        "type": "role_mask",
        "group": "Roles",
        "applies_to": ["moo"],
    },
    {
        "key": "population_size",
        "label": "Population size",
        "description": "Number of candidate balances kept per generation. Higher values improve search coverage and cost more time.",
        "type": "integer",
        "group": "Algorithm",
        "applies_to": ["moo"],
    },
    {
        "key": "generation_count",
        "label": "Generations",
        "description": "Maximum optimization iterations. Higher values can improve quality and increase runtime.",
        "type": "integer",
        "group": "Algorithm",
        "applies_to": ["moo"],
    },
    {
        "key": "mutation_rate",
        "label": "Mutation rate",
        "description": "Probability that a solution is changed while producing the next generation.",
        "type": "float",
        "group": "Algorithm",
        "applies_to": ["moo"],
    },
    {
        "key": "mutation_strength",
        "label": "Mutation strength",
        "description": "Number of swap/change operations attempted during a mutation.",
        "type": "integer",
        "group": "Algorithm",
        "applies_to": ["moo"],
    },
    {
        "key": "average_mmr_balance_weight",
        "label": "Average MMR balance",
        "description": "Penalty weight for differences between team average MMR values.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "team_total_balance_weight",
        "label": "Team total consistency",
        "description": "Penalty weight for standard deviation of total team rating sums.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "max_team_gap_weight",
        "label": "Max team gap",
        "description": "Penalty weight for the rating gap between the strongest and weakest teams.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "role_discomfort_weight",
        "label": "Role discomfort",
        "description": "Penalty weight for assigning players away from their preferred roles.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "max_role_discomfort_weight",
        "label": "Worst discomfort",
        "description": "Penalty weight for the single worst role discomfort assignment in a solution.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "role_line_balance_weight",
        "label": "Role line balance",
        "description": "Penalty weight for uneven rating strength between the same role across teams.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "sub_role_collision_weight",
        "label": "Subrole collision",
        "description": "Penalty weight per pair of players in the same team sharing the same role subclass.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "team_max_pain_weight",
        "label": "Per-team worst discomfort",
        "description": "Penalty weight for the per-team maximum role discomfort averaged over all teams.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "tank_impact_weight",
        "label": "Tank impact",
        "description": "Importance multiplier for Tank role contribution when comparing effective team totals.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "dps_impact_weight",
        "label": "Damage impact",
        "description": "Importance multiplier for Damage role contribution when comparing effective team totals.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "support_impact_weight",
        "label": "Support impact",
        "description": "Importance multiplier for Support role contribution when comparing effective team totals.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "tank_gap_weight",
        "label": "Tank gap weight",
        "description": "Penalty multiplier for the largest gap between adjacent (sorted by strength) Tank lines.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "tank_std_weight",
        "label": "Tank std weight",
        "description": "Penalty multiplier for Tank-line standard deviation across teams.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "effective_total_std_weight",
        "label": "Effective total std",
        "description": "Penalty multiplier for weighted effective team-total standard deviation.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "intra_team_std_weight",
        "label": "Intra-team rating std",
        "description": "Weight for rating spread inside each team.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "internal_role_spread_weight",
        "label": "Internal role spread",
        "description": "Penalty weight for uneven average strength between roles inside the same team.",
        "type": "float",
        "group": "Quality weights",
        "applies_to": ["moo"],
    },
    {
        "key": "use_captains",
        "label": "Use captains",
        "description": "Marks top-rated players as captains and uses them as team anchors when supported by the solver.",
        "type": "boolean",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "convergence_patience",
        "label": "Convergence patience",
        "description": "Generations without meaningful Pareto improvement before early stopping can trigger.",
        "type": "integer",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "convergence_epsilon",
        "label": "Convergence epsilon",
        "description": "Minimum relative improvement required to continue once convergence patience is reached.",
        "type": "float",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "mutation_rate_min",
        "label": "Mutation rate min",
        "description": "Lower bound for the adaptive mutation rate during Rust MOO search.",
        "type": "float",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "mutation_rate_max",
        "label": "Mutation rate max",
        "description": "Upper bound for the adaptive mutation rate during Rust MOO search.",
        "type": "float",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "island_count",
        "label": "Island count",
        "description": "Number of independent Rust MOO islands explored in parallel before merging the archive.",
        "type": "integer",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "polish_max_passes",
        "label": "Polish passes",
        "description": "Maximum local-improvement passes applied to each archive solution after the main search.",
        "type": "integer",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "greedy_seed_count",
        "label": "Greedy seed count",
        "description": "How many initial individuals are built with greedy seeding before random fill.",
        "type": "integer",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "stagnation_kick_patience",
        "label": "Stagnation kick",
        "description": "Generations without archive improvement before stronger mutation and crossover are applied.",
        "type": "integer",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "crossover_rate",
        "label": "Crossover rate",
        "description": "Probability of crossover when producing offspring in the Rust MOO search.",
        "type": "float",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "time_limit_ms",
        "label": "Time limit (ms)",
        "description": "Hard wall-clock budget for the optimizer. When exceeded, the best result found so far is returned. Trades same-seed reproducibility for latency.",
        "type": "integer",
        "group": "Strategy",
        "applies_to": ["moo"],
    },
    {
        "key": "max_result_variants",
        "label": "Result variants",
        "description": "Maximum number of solution variants returned by the selected solver.",
        "type": "integer",
        "group": "Solver output",
        "applies_to": ["moo"],
    },
]


def normalize_config_overrides(config_overrides: dict[str, typing.Any]) -> dict[str, typing.Any]:
    return normalize_external_config_overrides(config_overrides)


def normalize_tournament_config_payload(config_payload: dict[str, typing.Any] | None) -> dict[str, typing.Any]:
    from src.schemas.balancer import ConfigOverrides

    sanitized_payload = drop_legacy_public_config_keys(config_payload)
    if not sanitized_payload:
        return {}

    editable_payload: dict[str, typing.Any] = {}
    unknown_keys: dict[str, typing.Any] = {}

    for key, value in sanitized_payload.items():
        if key in EDITABLE_CONFIG_FIELD_KEYS:
            if value is not None:
                editable_payload[key] = value
            continue
        if key in SYSTEM_CONFIG_FIELD_KEYS:
            continue
        unknown_keys[key] = value

    if unknown_keys:
        ConfigOverrides.model_validate(unknown_keys)

    validated = ConfigOverrides.model_validate(editable_payload)
    return validated.model_dump(exclude_none=True)


def serialize_saved_config_payload(config_payload: dict[str, typing.Any] | None) -> dict[str, typing.Any]:
    return normalize_persisted_config_payload(config_payload)


def build_config_fields(defaults: dict[str, typing.Any]) -> list[dict[str, typing.Any]]:
    fields: list[dict[str, typing.Any]] = []
    for definition in CONFIG_FIELD_DEFINITIONS:
        key = definition["key"]
        fields.append(
            {
                **definition,
                "default": defaults.get(key),
                "limits": CONFIG_LIMITS.get(key),
            }
        )
    return fields


def get_balancer_config_payload() -> dict[str, typing.Any]:
    presets = {
        name: normalize_persisted_config_payload(value.copy())
        for name, value in ConfigPresets.__dict__.items()
        if name.isupper() and isinstance(value, dict)
    }
    defaults = serialize_algorithm_config(AlgorithmConfig())
    return {
        "defaults": defaults,
        "limits": CONFIG_LIMITS,
        "presets": presets,
        "fields": build_config_fields(defaults),
    }


class BalancerConfigService:
    def get_payload(self) -> dict:
        return get_balancer_config_payload()
