"""Validation helpers for public registration submissions."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException, status
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES, normalize_sub_role

from src.schemas.registration import (
    BuiltInFieldConfig,
    CustomFieldDefinition,
    RegistrationCreate,
    RegistrationUpdate,
)

BATTLE_TAG_FIELDS = {"battle_tag", "smurf_tags"}
TEXTUAL_CUSTOM_FIELD_TYPES = {"text", "number", "url"}

SubroleCatalog = dict[str, list[Any]]


def _catalog_slugs(catalog: SubroleCatalog | None, role_code: str) -> set[str]:
    slugs: set[str] = set()
    for option in (catalog or {}).get(role_code, []) or []:
        slug = option.get("slug") if isinstance(option, dict) else getattr(option, "slug", None)
        normalized = normalize_sub_role(slug)
        if normalized:
            slugs.add(normalized)
    return slugs


def _allowed_subroles(
    role_code: str,
    *,
    is_primary: bool,
    built_in_fields: dict[str, BuiltInFieldConfig],
    catalog: SubroleCatalog | None,
) -> set[str] | None:
    """Resolve the allowed sub-role slugs for a role, or ``None`` if unconstrained.

    Precedence mirrors the wizard: the per-tournament ``subroles`` selection on
    the matching role field wins; otherwise fall back to the workspace catalog.
    Returns ``None`` when nothing is configured anywhere (lenient — nothing to
    validate against).
    """
    field_key = "primary_role" if is_primary else "additional_roles"
    config = built_in_fields.get(field_key)
    configured = config.subroles.get(role_code) if config and config.subroles else None
    if configured is not None:
        return {normalize_sub_role(slug) for slug in configured if normalize_sub_role(slug)}

    catalog_slugs = _catalog_slugs(catalog, role_code)
    return catalog_slugs or None


def _validate_roles(
    roles: list[Any],
    *,
    built_in_fields: dict[str, BuiltInFieldConfig],
    catalog: SubroleCatalog | None,
) -> None:
    for role in roles:
        role_code = getattr(role, "role", None)
        if role_code not in REGISTRATION_ROLE_CODES:
            _validation_error(f"Invalid role: {role_code}.")

        subrole = normalize_sub_role(getattr(role, "subrole", None))
        if subrole is None:
            continue

        allowed = _allowed_subroles(
            role_code,
            is_primary=bool(getattr(role, "is_primary", False)),
            built_in_fields=built_in_fields,
            catalog=catalog,
        )
        if allowed is None:
            continue
        if subrole not in allowed:
            _validation_error(f"Invalid sub-role '{subrole}' for {role_code}.")


def _canonicalize_battle_tag(value: str | None) -> str:
    text = (value or "").strip()
    text = re.sub(r"\s*#\s*", "#", text)
    return text.replace(" ", "").strip()


def _coerce_built_in_field_config(value: Any) -> BuiltInFieldConfig:
    if isinstance(value, BuiltInFieldConfig):
        return value
    return BuiltInFieldConfig.model_validate(value or {})


def _coerce_custom_field_definition(value: Any) -> CustomFieldDefinition:
    if isinstance(value, CustomFieldDefinition):
        return value
    return CustomFieldDefinition.model_validate(value or {})


def _compile_fullmatch_pattern(pattern: str | None) -> re.Pattern[str] | None:
    if pattern is None:
        return None
    normalized = pattern.strip()
    if not normalized:
        return None
    return re.compile(normalized)


def _validation_error(
    message: str,
) -> None:
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=message)


def _matches_pattern(pattern: re.Pattern[str] | None, value: str) -> bool:
    if pattern is None:
        return True
    return pattern.fullmatch(value) is not None


def _validate_required_text(
    *,
    value: str | None,
    label: str,
) -> None:
    if (value or "").strip():
        return
    _validation_error(f"{label} is required.")


def _validate_required_list(
    *,
    values: list[str] | None,
    label: str,
) -> None:
    if values:
        return
    _validation_error(f"{label} is required.")


def _validate_string_pattern(
    *,
    value: str | None,
    config: BuiltInFieldConfig | CustomFieldDefinition,
    label: str,
    normalize_battle_tag: bool = False,
) -> None:
    raw_value = (value or "").strip()
    if not raw_value:
        return

    validation = config.validation
    pattern = _compile_fullmatch_pattern(validation.regex if validation else None)
    if pattern is None:
        return

    candidate = _canonicalize_battle_tag(raw_value) if normalize_battle_tag else raw_value
    if _matches_pattern(pattern, candidate):
        return

    _validation_error(validation.error_message or f"{label} format is invalid.")


def _validate_list_pattern(
    *,
    values: list[str] | None,
    config: BuiltInFieldConfig,
    label: str,
) -> None:
    if not values:
        return

    validation = config.validation
    pattern = _compile_fullmatch_pattern(validation.regex if validation else None)
    if pattern is None:
        return

    for value in values:
        candidate = _canonicalize_battle_tag(value)
        if candidate and _matches_pattern(pattern, candidate):
            continue
        _validation_error(validation.error_message or f"{label} format is invalid.")


def _validate_checkbox_requirement(
    *,
    value: Any,
    field: CustomFieldDefinition,
) -> None:
    if value is not None and value != "":
        return
    _validation_error(f"Fill in the required field: {field.label}.")


def _validate_custom_field(
    *,
    field: CustomFieldDefinition,
    value: Any,
    provided: bool,
    partial: bool,
) -> None:
    if partial and not provided:
        return

    if field.required:
        if field.type == "checkbox":
            _validate_checkbox_requirement(value=value, field=field)
        elif not str(value or "").strip():
            _validation_error(f"Fill in the required field: {field.label}.")

    if field.type not in TEXTUAL_CUSTOM_FIELD_TYPES:
        return

    _validate_string_pattern(
        value=None if value is None else str(value),
        config=field,
        label=field.label,
    )


def validate_registration_input(
    form: Any,
    payload: RegistrationCreate | RegistrationUpdate,
    *,
    partial: bool = False,
    subrole_catalog: SubroleCatalog | None = None,
) -> None:
    built_in_fields = {
        key: _coerce_built_in_field_config(value)
        for key, value in (getattr(form, "built_in_fields_json", None) or {}).items()
    }
    custom_fields = [
        _coerce_custom_field_definition(value) for value in (getattr(form, "custom_fields_json", None) or [])
    ]
    provided_fields = payload.model_fields_set if partial else None

    built_in_payload_values: dict[str, Any] = {
        "battle_tag": getattr(payload, "battle_tag", None),
        "smurf_tags": getattr(payload, "smurf_tags", None),
        "discord_nick": getattr(payload, "discord_nick", None),
        "twitch_nick": getattr(payload, "twitch_nick", None),
        "notes": getattr(payload, "notes", None),
        "stream_pov": getattr(payload, "stream_pov", None),
        "roles": getattr(payload, "roles", None),
    }

    for field_key, label in (
        ("battle_tag", "BattleTag"),
        ("smurf_tags", "Smurf Accounts"),
        ("discord_nick", "Discord"),
        ("twitch_nick", "Twitch"),
        ("notes", "Notes"),
    ):
        config = built_in_fields.get(field_key)
        if config is None or not config.enabled:
            continue
        if partial and provided_fields is not None and field_key not in provided_fields:
            continue

        value = built_in_payload_values[field_key]
        if config.required:
            if field_key == "smurf_tags":
                _validate_required_list(values=value, label=label)
            else:
                _validate_required_text(value=value, label=label)

        if field_key == "smurf_tags":
            _validate_list_pattern(values=value, config=config, label=label)
        else:
            _validate_string_pattern(
                value=value,
                config=config,
                label=label,
                normalize_battle_tag=field_key in BATTLE_TAG_FIELDS,
            )

    primary_role_config = built_in_fields.get("primary_role")
    if primary_role_config and primary_role_config.enabled and primary_role_config.required:
        if not partial or (provided_fields is not None and "roles" in provided_fields):
            roles = built_in_payload_values["roles"] or []
            if not any(getattr(role, "is_primary", False) for role in roles):
                _validation_error("Primary Role is required.")

    additional_roles_config = built_in_fields.get("additional_roles")
    if additional_roles_config and additional_roles_config.enabled and additional_roles_config.required:
        if not partial or (provided_fields is not None and "roles" in provided_fields):
            roles = built_in_payload_values["roles"] or []
            is_flex = bool(roles) and all(getattr(role, "is_primary", False) for role in roles)
            if not is_flex and not any(not getattr(role, "is_primary", False) for role in roles):
                _validation_error("At least one additional role is required.")

    # Validate role codes and sub-roles against the workspace catalog / form config.
    submitted_roles = built_in_payload_values["roles"]
    if submitted_roles is not None:
        _validate_roles(
            submitted_roles,
            built_in_fields=built_in_fields,
            catalog=subrole_catalog,
        )

    custom_values = getattr(payload, "custom_fields", None) or {}
    if not isinstance(custom_values, dict):
        custom_values = {}

    for field in custom_fields:
        provided = field.key in custom_values
        _validate_custom_field(
            field=field,
            value=custom_values.get(field.key),
            provided=provided,
            partial=partial,
        )
