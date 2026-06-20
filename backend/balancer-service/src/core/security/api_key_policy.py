from __future__ import annotations

from typing import Any

from shared.core.errors import BaseAPIException as HTTPException
from shared.core import http_status as status

from src.core.security.api_key_limiter import is_api_key_principal

DEFAULT_CONFIG_POLICY: dict[str, Any] = {
    "allowed_keys": [
        "role_mask",
        "population_size",
        "generation_count",
        "use_captains",
        "max_result_variants",
    ],
    "max_values": {
        "population_size": 150,
        "generation_count": 500,
        "max_result_variants": 10,
    },
}


def _policy_for_user(user: Any) -> dict[str, Any]:
    payload = getattr(user, "_api_key_config_policy", None)
    if not isinstance(payload, dict):
        return DEFAULT_CONFIG_POLICY
    policy = dict(DEFAULT_CONFIG_POLICY)
    policy.update(payload)
    return policy


def validate_api_key_config_policy(user: Any, config_overrides: dict[str, Any] | None) -> None:
    if not is_api_key_principal(user) or not config_overrides:
        return

    policy = _policy_for_user(user)
    allowed_keys = set(policy.get("allowed_keys") or [])
    max_values = policy.get("max_values") if isinstance(policy.get("max_values"), dict) else {}

    for key, value in config_overrides.items():
        if key not in allowed_keys:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "api_key_config_field_not_allowed",
                    "field": key,
                    "allowed_fields": sorted(allowed_keys),
                },
            )
        if key in max_values and value is not None:
            try:
                numeric_value = float(value)
                numeric_limit = float(max_values[key])
            except (TypeError, ValueError):
                continue
            if numeric_value > numeric_limit:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "api_key_config_value_too_high",
                        "field": key,
                        "max": max_values[key],
                    },
                )
