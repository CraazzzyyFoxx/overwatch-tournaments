"""Role composition, sub-role and top-hero rules for the ``roles`` builtin.

The schema pipeline (``shared/domain/forms/validate.py``) can coerce a roles
answer structurally, but not judge it: the rules need the workspace sub-role
catalog and the hero catalog, both of which come from the database. So they
live here, as the tournament-service plugin the pipeline calls after
normalisation.

Every rule RETURNS a :class:`FieldError` instead of raising, and every rule
runs: a registrant sees the whole verdict on one round trip rather than the
first complaint. The order of the collected errors is the order the old
first-failure validator would have raised them in.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from shared.core import enums
from shared.domain.forms.builtins import RolesParams
from shared.domain.forms.schema import FormField
from shared.domain.forms.validate import ErrorCode, FieldError
from shared.domain.player_sub_roles import (
    REGISTRATION_ROLE_CODES,
    REGISTRATION_TO_CANONICAL,
    normalize_sub_role,
)
from shared.hero_catalog import DEFAULT_MAX_TOP_HEROES, HeroCatalog

__all__ = ("SubroleCatalog", "is_flex_submission", "role_value", "validate_roles")

#: The one field key these errors are reported against.
FIELD = "roles"

_ROLE_LABELS = {"tank": "Tank", "damage": "DPS", "support": "Support"}
_HERO_CLASS_BY_CANONICAL = {
    "tank": enums.HeroClass.tank,
    "damage": enums.HeroClass.damage,
    "support": enums.HeroClass.support,
}

SubroleCatalog = dict[str, list[Any]]


def _err(code: str, msg: str, **params: Any) -> FieldError:
    return FieldError(field=FIELD, code=code, msg=msg, params=MappingProxyType(params))


def role_value(role: Any, key: str, default: Any = None) -> Any:
    """One submitted role row's field.

    Rows arrive as dicts from the answer pipeline; ``serializers.py`` reads the
    same shape off ORM ``BalancerRegistrationRole`` objects through
    ``is_flex_submission``, so attribute rows are read too.
    """
    if isinstance(role, Mapping):
        return role.get(key, default)
    return getattr(role, key, default)


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
    params: RolesParams,
    catalog: SubroleCatalog | None,
) -> set[str] | None:
    """The allowed sub-role slugs for a role, or ``None`` if unconstrained.

    Precedence mirrors the wizard: the per-tournament ``subroles`` selection on
    the ``roles`` field wins; otherwise fall back to the workspace catalog.
    Returns ``None`` when nothing is configured anywhere (lenient — nothing to
    validate against). A configured *empty* list is a constraint, not an
    absence: it allows nothing, exactly as the pre-schema config did.
    """
    configured = params.subroles.get(role_code)
    if configured is not None:
        return {slug for slug in (normalize_sub_role(raw) for raw in configured) if slug}

    catalog_slugs = _catalog_slugs(catalog, role_code)
    return catalog_slugs or None


def is_flex_submission(roles: list[dict[str, Any]]) -> bool:
    """A flex registration selects every role as primary.

    Requires more than one role so a lone primary role (a normal single-role
    registration) is *not* treated as flex — only the wizard's full-flex
    submission (all roles, each primary) qualifies.
    """
    return len(roles) > 1 and all(role_value(role, "is_primary", False) for role in roles)


def _resolve_max_heroes(params: RolesParams) -> int:
    configured = params.top_heroes.max
    if configured is not None and configured > 0:
        return configured
    return DEFAULT_MAX_TOP_HEROES


def _role_errors(
    roles: list[dict[str, Any]],
    *,
    params: RolesParams,
    catalog: SubroleCatalog | None,
) -> list[FieldError]:
    """Role codes and sub-roles, one verdict per submitted row."""
    errors: list[FieldError] = []
    for role in roles:
        role_code = role_value(role, "role")
        if role_code not in REGISTRATION_ROLE_CODES:
            errors.append(_err("roles.unknown_role", f"Invalid role: {role_code}.", role=role_code))
            continue

        subrole = normalize_sub_role(role_value(role, "subrole"))
        if subrole is None:
            continue

        allowed = _allowed_subroles(role_code, params=params, catalog=catalog)
        if allowed is None or subrole in allowed:
            continue
        errors.append(
            _err(
                "roles.subrole_not_allowed",
                f"Invalid sub-role '{subrole}' for {role_code}.",
                role=role_code,
                subrole=subrole,
            )
        )
    return errors


def _hero_errors(
    roles: list[dict[str, Any]],
    *,
    params: RolesParams,
    hero_catalog: HeroCatalog,
) -> list[FieldError]:
    """The optional ``top_heroes`` slugs submitted for each role.

    Enforces (per role): the configured max, no duplicates, existence in the
    hero catalog, and — for non-flex registrations — that the hero's class
    matches the role. Flex registrations accept heroes of any class.
    """
    if not params.top_heroes.enabled:
        return []

    errors: list[FieldError] = []
    max_heroes = _resolve_max_heroes(params)
    is_flex = is_flex_submission(roles)
    any_selected = False

    for role in roles:
        slugs = role_value(role, "top_heroes")
        if not slugs:
            continue
        any_selected = True
        role_code = role_value(role, "role")

        if len(slugs) > max_heroes:
            errors.append(
                _err(
                    "roles.too_many_heroes",
                    f"You can select at most {max_heroes} heroes per role.",
                    role=role_code,
                    max=max_heroes,
                )
            )
        if len(set(slugs)) != len(slugs):
            errors.append(
                _err(
                    ErrorCode.INVALID_OPTION.value,
                    "Duplicate heroes are not allowed.",
                    role=role_code,
                )
            )

        expected_class = None
        if not is_flex:
            canonical = REGISTRATION_TO_CANONICAL.get(role_code) if role_code else None
            expected_class = _HERO_CLASS_BY_CANONICAL.get(canonical) if canonical else None

        for slug in slugs:
            entry = hero_catalog.get(slug)
            if entry is None:
                errors.append(_err(ErrorCode.INVALID_OPTION.value, f"Unknown hero: {slug}.", hero=slug))
                continue
            if expected_class is not None and entry.hero_class != expected_class:
                errors.append(
                    _err(
                        "roles.hero_wrong_class",
                        f"Hero '{slug}' is not a {_ROLE_LABELS.get(role_code, role_code)} hero.",
                        role=role_code,
                        hero=slug,
                    )
                )

    if params.top_heroes.required and not any_selected:
        errors.append(_err(ErrorCode.REQUIRED.value, "Select at least one top hero."))

    return errors


def validate_roles(
    field: FormField,
    roles: list[dict[str, Any]],
    *,
    subrole_catalog: SubroleCatalog | None,
    hero_catalog: HeroCatalog | None,
) -> list[FieldError]:
    """Every rule the ``roles`` builtin enforces, collected.

    ``field`` is the schema's ``roles`` field; its ``params`` carry the
    organizer's configuration. ``roles`` is the normalised answer — a list of
    ``{role, subrole?, is_primary, top_heroes?}``.
    """
    params = RolesParams.model_validate(field.params)
    errors: list[FieldError] = []

    if params.primary_required and not any(role_value(role, "is_primary", False) for role in roles):
        errors.append(_err("roles.primary_required", "Primary Role is required."))

    if params.additional_required:
        # "Covers more than the priority role": either an explicit non-primary
        # row, or a full-flex submission (>1 role, every one primary).
        covers_additional = is_flex_submission(roles) or any(
            not role_value(role, "is_primary", False) for role in roles
        )
        if not covers_additional:
            errors.append(_err("roles.additional_required", "At least one additional role is required."))

    errors.extend(_role_errors(roles, params=params, catalog=subrole_catalog))

    # Flex availability guard: when the organizer disabled the Flex role,
    # reject an all-primary (full-flex) submission.
    if not params.flex_allowed and is_flex_submission(roles):
        errors.append(_err("roles.flex_unavailable", "Flex registration is not available for this tournament."))

    # ``all_roles``: every role is mandatory and the registrant names exactly
    # one priority role, or declares flex (every role primary). Anything in
    # between is a client that lost the choice, not a preference we can guess
    # — the write-path normalizer backfills the role SET but cannot invent
    # which role the registrant meant.
    if params.flex_mode == "all_roles":
        primary_count = sum(1 for role in roles if role_value(role, "is_primary", False))
        if primary_count not in (1, len(REGISTRATION_ROLE_CODES)):
            errors.append(_err("roles.one_priority_or_flex", "Choose one priority role, or Flex."))

    if hero_catalog is not None:
        errors.extend(_hero_errors(roles, params=params, hero_catalog=hero_catalog))

    return errors
