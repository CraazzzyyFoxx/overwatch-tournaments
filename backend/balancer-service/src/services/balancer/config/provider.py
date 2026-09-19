"""The ``GET /balancer/config`` payload and the tournament-config write path.

Nothing here declares a knob. The editable set, its bounds and its drawer
metadata are all read off :class:`AlgorithmConfig`, so a new knob is one
``Field(..., json_schema_extra=knob(...))`` and it shows up everywhere at once.
"""

from __future__ import annotations

import typing

from src.services.balancer.config.defaults import (
    AlgorithmConfig,
    field_control,
    field_limits,
    field_ui,
)
from src.services.balancer.config.presets import ConfigPresets
from src.services.balancer.config.public_contract import (
    RETIRED_CONFIG_KEYS,
    ConfigOverrides,
    normalize_config_payload,
    serialize_algorithm_config,
)

#: Knobs carrying a ``knob`` block: what the config drawer renders and what a
#: tournament config may contain.
EDITABLE_CONFIG_FIELDS = {
    name: field for name, field in AlgorithmConfig.model_fields.items() if field_ui(field) is not None
}

EDITABLE_CONFIG_FIELD_KEYS = frozenset(EDITABLE_CONFIG_FIELDS)

#: UI slider/input bounds, read off each knob's own constraints -- so the drawer
#: cannot advertise a range the request would then reject.
CONFIG_LIMITS: dict[str, dict[str, int | float]] = {
    name: limits for name, field in EDITABLE_CONFIG_FIELDS.items() if (limits := field_limits(field))
}

# Request-envelope keys the frontend stores next to the knobs in ``config_json``:
# they say which config this is, they are not part of it.
SYSTEM_CONFIG_FIELD_KEYS = frozenset({"workspace_id", "tournament_id", "division_grid", "division_scope"})


def normalize_tournament_config_payload(config_payload: dict[str, typing.Any] | None) -> dict[str, typing.Any]:
    """Validate the operator-facing tournament config. Strict on purpose.

    A key that is neither a knob, a retired knob nor an envelope field is a
    typo, and a typo that silently does nothing is worse than a 422 --
    ``ConfigOverrides`` has ``extra="forbid"`` and raises. Non-editable knobs
    (``mix_*``) validate but are then dropped: the drawer cannot set them and
    ``tournament_balancer`` never reads them.
    """
    candidate_payload = {
        key: value
        for key, value in (config_payload or {}).items()
        if key not in RETIRED_CONFIG_KEYS and key not in SYSTEM_CONFIG_FIELD_KEYS
    }
    if not candidate_payload:
        return {}

    validated = ConfigOverrides.model_validate(candidate_payload).model_dump(exclude_none=True)
    return {key: value for key, value in validated.items() if key in EDITABLE_CONFIG_FIELD_KEYS}


def build_config_fields(defaults: dict[str, typing.Any]) -> list[dict[str, typing.Any]]:
    """One drawer row per editable knob: label, help text, widget, bounds, default."""
    return [
        {
            "key": name,
            "label": ui["label"],
            "description": field.description or "",
            "type": field_control(field),
            "group": ui["group"],
            "default": defaults.get(name),
            "limits": CONFIG_LIMITS.get(name),
        }
        for name, field in EDITABLE_CONFIG_FIELDS.items()
        # Always true -- a field is in this dict precisely because it has a
        # ``knob`` block; the guard is how the comprehension binds it.
        if (ui := field_ui(field))
    ]


def get_balancer_config_payload() -> dict[str, typing.Any]:
    defaults = serialize_algorithm_config(AlgorithmConfig())
    return {
        "defaults": defaults,
        "limits": CONFIG_LIMITS,
        "presets": {
            name: normalize_config_payload(value)
            for name, value in ConfigPresets.__dict__.items()
            if name.isupper() and isinstance(value, dict)
        },
        "fields": build_config_fields(defaults),
    }
