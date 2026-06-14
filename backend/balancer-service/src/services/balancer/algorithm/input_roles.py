from __future__ import annotations

from collections.abc import Mapping

STANDARD_ROLE_CODES: dict[str, str] = {
    "tank": "tank",
    "damage": "dps",
    "dps": "dps",
    "support": "support",
}


def normalize_standard_role_code(raw_role: str | None) -> str | None:
    if raw_role is None:
        return None

    return STANDARD_ROLE_CODES.get(raw_role.strip().lower())


def resolve_input_role_name(raw_role: str | None, role_mask: Mapping[str, int]) -> str | None:
    if raw_role is None:
        return None

    normalized_value = raw_role.strip()
    if not normalized_value:
        return None

    if normalized_value in role_mask:
        return normalized_value

    lowered_value = normalized_value.lower()
    for role_name in role_mask:
        if role_name.lower() == lowered_value:
            return role_name

    normalized_code = normalize_standard_role_code(normalized_value)
    if normalized_code is None:
        return None

    for role_name in role_mask:
        if normalize_standard_role_code(role_name) == normalized_code:
            return role_name

    return None
