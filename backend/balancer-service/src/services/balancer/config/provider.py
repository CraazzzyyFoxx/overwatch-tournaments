"""The ``GET /balancer/config`` payload and the tournament-config write path.

Nothing here declares a knob. The editable set, its bounds and its drawer
metadata are all read off :class:`AlgorithmConfig`, so a new knob is one
``Field(..., json_schema_extra=knob(...))`` and it shows up everywhere at once.
"""

from __future__ import annotations

import typing

from src.services.balancer.config.defaults import (
    MIX_ONLY_ROLE_FIELDS,
    AlgorithmConfig,
    RoleSettings,
    field_control,
    field_limits,
    field_ui,
    tournament_role_settings,
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

#: The ``role_settings`` row is a table, not a single value: one column per
#: setting a tournament config carries, labelled and bounded off
#: :class:`RoleSettings` itself so the drawer cannot advertise a field or a range
#: the request would reject.
ROLE_SETTING_COLUMNS: list[dict[str, typing.Any]] = [
    {
        "key": name,
        "label": field.title,
        "description": field.description or "",
        "limits": field_limits(field),
    }
    for name, field in RoleSettings.model_fields.items()
    if name not in MIX_ONLY_ROLE_FIELDS
]


def normalize_tournament_config_payload(config_payload: dict[str, typing.Any] | None) -> dict[str, typing.Any]:
    """Validate the operator-facing tournament config. Strict on purpose.

    A key that is neither a knob, a retired knob nor an envelope field is a
    typo, and a typo that silently does nothing is worse than a 422 --
    ``ConfigOverrides`` has ``extra="forbid"`` and raises. Non-editable knobs
    (``mix_*``, and ``mix_weight`` inside ``role_settings``) validate but are then
    dropped: the drawer cannot set them and ``tournament_balancer`` never reads them.
    """
    candidate_payload = {
        key: value
        for key, value in (config_payload or {}).items()
        if key not in RETIRED_CONFIG_KEYS and key not in SYSTEM_CONFIG_FIELD_KEYS
    }
    if not candidate_payload:
        return {}

    validated = ConfigOverrides.model_validate(candidate_payload).model_dump(exclude_none=True)
    config = {key: value for key, value in validated.items() if key in EDITABLE_CONFIG_FIELD_KEYS}
    if role_settings := config.get("role_settings"):
        config["role_settings"] = {
            code: kept
            for code, settings in role_settings.items()
            if (kept := {key: value for key, value in settings.items() if key not in MIX_ONLY_ROLE_FIELDS})
        }
    return config


def build_config_fields(defaults: dict[str, typing.Any]) -> list[dict[str, typing.Any]]:
    """One drawer row per editable knob: label, help text, widget, bounds, default.

    A ``roles`` row is a table rather than a single input, so it carries its
    columns instead of ``limits`` (which belong to each column).
    """
    rows: list[dict[str, typing.Any]] = []
    for name, field in EDITABLE_CONFIG_FIELDS.items():
        # Always true -- a field is in this dict precisely because it has a
        # ``knob`` block.
        ui = field_ui(field) or {}
        control = field_control(field)
        row: dict[str, typing.Any] = {
            "key": name,
            "label": ui["label"],
            "description": field.description or "",
            "type": control,
            "group": ui["group"],
            "default": defaults.get(name),
            "limits": CONFIG_LIMITS.get(name),
        }
        if control == "roles":
            row["columns"] = ROLE_SETTING_COLUMNS
        rows.append(row)
    return rows


def get_balancer_config_payload() -> dict[str, typing.Any]:
    config = AlgorithmConfig()
    # The drawer edits the tournament projection, so the defaults it draws must be
    # that same projection -- not the mix engine's copy of the per-role weights.
    defaults = serialize_algorithm_config(config) | {"role_settings": tournament_role_settings(config.role_settings)}
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
