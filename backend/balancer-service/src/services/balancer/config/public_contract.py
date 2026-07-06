from __future__ import annotations

import typing
from collections.abc import Mapping

from pydantic import ValidationError

from src.services.balancer.config.defaults import AlgorithmConfig

PUBLIC_CONFIG_KEYS = {
    "role_mask",
    "algorithm",
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
    "rank_comfort_tilt",
}

LEGACY_PUBLIC_CONFIG_KEYS = {
    "input_role_mapping",
    "elitism_rate",
    "stagnation_threshold",
    # Никогда не читались вычислениями (живые веса — intra_team_std_weight и
    # internal_role_spread_weight); выпилены из конфига, но могут встречаться
    # в сохранённых турнирных конфигах — молча отбрасываем.
    "intra_team_variance_weight",
    "role_spread_weight",
}


def drop_legacy_public_config_keys(config_payload: Mapping[str, typing.Any] | None) -> dict[str, typing.Any]:
    if not config_payload:
        return {}

    return {key: value for key, value in dict(config_payload).items() if key not in LEGACY_PUBLIC_CONFIG_KEYS}


def normalize_persisted_config_payload(config_payload: Mapping[str, typing.Any] | None) -> dict[str, typing.Any]:
    from src.schemas.balancer import ConfigOverrides

    sanitized_payload = {
        key: value for key, value in drop_legacy_public_config_keys(config_payload).items() if key in PUBLIC_CONFIG_KEYS
    }
    if not sanitized_payload:
        return {}

    if "algorithm" in sanitized_payload:
        try:
            ConfigOverrides.model_validate({"algorithm": sanitized_payload["algorithm"]})
        except ValidationError:
            sanitized_payload.pop("algorithm", None)

    validated = ConfigOverrides.model_validate(sanitized_payload)
    return validated.model_dump(exclude_none=True)


def normalize_config_overrides(config_overrides: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    return normalize_persisted_config_payload(config_overrides)


def serialize_algorithm_config(config: AlgorithmConfig | Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    payload = config.model_dump() if hasattr(config, "model_dump") else dict(config)
    return {key: value for key, value in payload.items() if key in PUBLIC_CONFIG_KEYS and value is not None}


def normalize_balance_response_payload(balance_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    from src.schemas.balancer import BalanceResponse

    validated = BalanceResponse.model_validate(dict(balance_payload))
    return validated.model_dump(exclude_none=True)


def normalize_balance_job_result_payload(result_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    from src.schemas.balancer import BalanceJobResult

    validated = BalanceJobResult.model_validate(dict(result_payload))
    return validated.model_dump(exclude_none=True)
