from __future__ import annotations

import typing
from collections.abc import Mapping

from pydantic import ValidationError

from src.services.balancer.config.defaults import AlgorithmConfig

# ``role_mask`` is deliberately absent: a saved config must not be able to
# contradict the tournament's roster shape, which is resolved per run.
PUBLIC_CONFIG_KEYS = {
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
    "low_rank_threshold",
    "low_rank_collision_weight",
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
    # mix_balancer only; kept public so a mix's saved overrides survive
    # ``normalize_persisted_config_payload``, which drops anything not listed here.
    "mix_comfort_tilt",
    "mix_role_weights",
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


# Balances saved before the result payload was renamed to snake_case still sit in
# ``balancer_balance.result_json``; reads upgrade them in place so old rows stay
# loadable (the current schema itself stays snake_case-only).
_LEGACY_TEAM_KEYS = {
    "avgMMR": "average_mmr",
    "variance": "rating_variance",
    "totalDiscomfort": "total_discomfort",
    "maxDiscomfort": "max_discomfort",
}
_LEGACY_PLAYER_KEYS = {
    "rating": "assigned_rating",
    "discomfort": "role_discomfort",
    "isCaptain": "is_captain",
    "preferences": "role_preferences",
    "allRatings": "all_ratings",
    "isFlex": "is_flex",
    "subRole": "sub_role",
}
_LEGACY_STATISTICS_KEYS = {
    "averageMMR": "average_mmr",
    "mmrStdDev": "mmr_std_dev",
    "totalTeams": "total_teams",
    "playersPerTeam": "players_per_team",
    "offRoleCount": "off_role_count",
    "subRoleCollisionCount": "sub_role_collision_count",
    "unbalancedCount": "unbalanced_count",
}
_LEGACY_ROOT_KEYS = {
    "benchedPlayers": "benched_players",
    "appliedConfig": "applied_config",
}


def _rename_legacy_keys(payload: Mapping[str, typing.Any], legacy_keys: Mapping[str, str]) -> dict[str, typing.Any]:
    upgraded = {key: value for key, value in payload.items() if key not in legacy_keys}
    for legacy_key, key in legacy_keys.items():
        if legacy_key in payload and key not in upgraded:
            upgraded[key] = payload[legacy_key]
    return upgraded


def _upgrade_legacy_player(player: typing.Any) -> typing.Any:
    if not isinstance(player, Mapping):
        return player
    return _rename_legacy_keys(player, _LEGACY_PLAYER_KEYS)


def _upgrade_legacy_team(team: typing.Any) -> typing.Any:
    if not isinstance(team, Mapping):
        return team
    upgraded = _rename_legacy_keys(team, _LEGACY_TEAM_KEYS)
    roster = upgraded.get("roster")
    if isinstance(roster, Mapping):
        upgraded["roster"] = {
            role: [_upgrade_legacy_player(player) for player in players] if isinstance(players, list) else players
            for role, players in roster.items()
        }
    return upgraded


def upgrade_legacy_balance_payload(balance_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    upgraded = _rename_legacy_keys(balance_payload, _LEGACY_ROOT_KEYS)
    teams = upgraded.get("teams")
    if isinstance(teams, list):
        upgraded["teams"] = [_upgrade_legacy_team(team) for team in teams]
    benched = upgraded.get("benched_players")
    if isinstance(benched, list):
        upgraded["benched_players"] = [_upgrade_legacy_player(player) for player in benched]
    statistics = upgraded.get("statistics")
    if isinstance(statistics, Mapping):
        upgraded["statistics"] = _rename_legacy_keys(statistics, _LEGACY_STATISTICS_KEYS)
    return upgraded


def normalize_balance_response_payload(balance_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    from src.schemas.balancer import BalanceResponse

    validated = BalanceResponse.model_validate(upgrade_legacy_balance_payload(balance_payload))
    return validated.model_dump(exclude_none=True)


def normalize_balance_job_result_payload(result_payload: Mapping[str, typing.Any]) -> dict[str, typing.Any]:
    from src.schemas.balancer import BalanceJobResult

    validated = BalanceJobResult.model_validate(dict(result_payload))
    return validated.model_dump(exclude_none=True)
