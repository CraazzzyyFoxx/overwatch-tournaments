"""Validation helpers for public registration submissions."""

from __future__ import annotations

import re
from typing import Any, NoReturn

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider, normalize_social_handle
from shared.domain.player_sub_roles import (
    REGISTRATION_ROLE_CODES,
    REGISTRATION_TO_CANONICAL,
    normalize_sub_role,
)
from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, HeroCatalog
from shared.models.identity.social import SocialAccount
from src.schemas.registration import (
    BuiltInFieldConfig,
    CustomFieldDefinition,
    RegistrationCreate,
    RegistrationUpdate,
)

BATTLE_TAG_FIELDS = {"battle_tag", "smurf_tags"}
TEXTUAL_CUSTOM_FIELD_TYPES = {"text", "number", "url"}

# Identity registration fields that can require an OAuth-verified social account,
# mapped to the canonical social provider their submitted handle must match.
VERIFIED_FIELD_PROVIDERS: dict[str, str] = {
    "battle_tag": SocialProvider.BATTLENET,
    "discord_nick": SocialProvider.DISCORD,
    "twitch_nick": SocialProvider.TWITCH,
}
_VERIFIED_FIELD_LABELS = {
    "battle_tag": "BattleTag",
    "discord_nick": "Discord",
    "twitch_nick": "Twitch",
}

_ROLE_LABELS = {"tank": "Tank", "dps": "DPS", "support": "Support"}
_HERO_CLASS_BY_CANONICAL = {
    "tank": enums.HeroClass.tank,
    "damage": enums.HeroClass.damage,
    "support": enums.HeroClass.support,
}

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


def _is_flex_submission(roles: list[Any]) -> bool:
    """A flex registration selects every role as primary.

    Requires more than one role so a lone primary role (a normal single-role
    registration) is *not* treated as flex — only the wizard's full-flex
    submission (all roles, each primary) qualifies.
    """
    return len(roles) > 1 and all(getattr(role, "is_primary", False) for role in roles)


def _resolve_max_heroes(config: BuiltInFieldConfig) -> int:
    if config.max_heroes is not None and config.max_heroes > 0:
        return config.max_heroes
    return DEFAULT_MAX_TOP_HEROES


def _validate_role_heroes(
    roles: list[Any],
    *,
    built_in_fields: dict[str, BuiltInFieldConfig],
    hero_catalog: HeroCatalog,
) -> None:
    """Validate the optional ``top_heroes`` slugs submitted for each role.

    Enforces (per role): the configured max, no duplicates, existence in the
    hero catalog, and — for non-flex registrations — that the hero's class
    matches the role. Flex registrations accept heroes of any class.
    """
    config = built_in_fields.get("top_heroes")
    if config is None or not config.enabled:
        return

    max_heroes = _resolve_max_heroes(config)
    is_flex = _is_flex_submission(roles)
    any_selected = False

    for role in roles:
        slugs = getattr(role, "top_heroes", None)
        if not slugs:
            continue
        any_selected = True
        role_code = getattr(role, "role", None)

        if len(slugs) > max_heroes:
            _validation_error(f"You can select at most {max_heroes} heroes per role.")
        if len(set(slugs)) != len(slugs):
            _validation_error("Duplicate heroes are not allowed.")

        expected_class = None
        if not is_flex:
            canonical = REGISTRATION_TO_CANONICAL.get(role_code) if role_code else None
            expected_class = _HERO_CLASS_BY_CANONICAL.get(canonical) if canonical else None

        for slug in slugs:
            entry = hero_catalog.get(slug)
            if entry is None:
                _validation_error(f"Unknown hero: {slug}.")
            if expected_class is not None and entry.hero_class != expected_class:
                _validation_error(f"Hero '{slug}' is not a {_ROLE_LABELS.get(role_code, role_code)} hero.")

    if config.required and not any_selected:
        _validation_error("Select at least one top hero.")


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
) -> NoReturn:
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
    hero_catalog: HeroCatalog | None = None,
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

        # Flex availability guard: when the organizer disabled the Flex role,
        # reject an all-primary (full-flex) submission.
        flex_config = built_in_fields.get("flex_role")
        if flex_config is not None and not flex_config.enabled and _is_flex_submission(submitted_roles):
            _validation_error("Flex registration is not available for this tournament.")

        if hero_catalog is not None:
            _validate_role_heroes(
                submitted_roles,
                built_in_fields=built_in_fields,
                hero_catalog=hero_catalog,
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


async def validate_verified_identity(
    session: AsyncSession,
    *,
    form: Any,
    payload: RegistrationCreate | RegistrationUpdate,
    player_id: int | None,
    partial: bool = False,
) -> None:
    """Enforce ``require_verified`` identity fields against the registrant's
    OAuth-verified social accounts.

    A field flagged ``require_verified`` must carry a handle matching one of the
    registrant's verified ``social_account`` rows for the field's provider.
    Ownership is proven only via OAuth (see identity-service), so a registrant
    with no linked player — or no verified account for the provider — is rejected.
    ``require_verified`` implies the field is required.
    """
    built_in_fields = {
        key: _coerce_built_in_field_config(value)
        for key, value in (getattr(form, "built_in_fields_json", None) or {}).items()
    }
    provided_fields = payload.model_fields_set if partial else None

    # (field_key, provider, submitted_value) for every gated, in-scope field.
    required: list[tuple[str, str, str]] = []
    for field_key, provider in VERIFIED_FIELD_PROVIDERS.items():
        config = built_in_fields.get(field_key)
        if config is None or not config.enabled or not config.require_verified:
            continue
        if partial and provided_fields is not None and field_key not in provided_fields:
            continue
        label = _VERIFIED_FIELD_LABELS[field_key]
        value = getattr(payload, field_key, None)
        if not value or not str(value).strip():
            _validation_error(f"{label} must be provided and verified via OAuth.")
        required.append((field_key, provider, str(value)))

    if not required:
        return

    if player_id is None:
        _validation_error("A verified account is required. Link the requested account via OAuth in your profile first.")

    providers = {provider for _, provider, _ in required}
    rows = (
        await session.execute(
            select(SocialAccount.provider, SocialAccount.username_normalized).where(
                SocialAccount.user_id == player_id,
                SocialAccount.provider.in_(providers),
                SocialAccount.is_verified.is_(True),
            )
        )
    ).all()
    verified_by_provider: dict[str, set[str]] = {provider: set() for provider in providers}
    for provider, normalized in rows:
        if normalized:
            verified_by_provider.setdefault(provider, set()).add(normalized)

    for field_key, provider, value in required:
        label = _VERIFIED_FIELD_LABELS[field_key]
        if normalize_social_handle(provider, value) not in verified_by_provider.get(provider, set()):
            _validation_error(f"{label} must match an OAuth-verified account linked to your profile.")
