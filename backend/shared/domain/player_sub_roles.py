from __future__ import annotations

import re
from collections.abc import Iterable
from enum import Enum
from typing import Any, Protocol

LEGACY_HITSCAN_SUB_ROLE = "hitscan"
LEGACY_PROJECTILE_SUB_ROLE = "projectile"
LEGACY_MAIN_HEAL_SUB_ROLE = "main_heal"
LEGACY_LIGHT_HEAL_SUB_ROLE = "light_heal"

LEGACY_PRIMARY_SUB_ROLES = frozenset(
    {LEGACY_HITSCAN_SUB_ROLE, LEGACY_MAIN_HEAL_SUB_ROLE}
)
LEGACY_SECONDARY_SUB_ROLES = frozenset(
    {LEGACY_PROJECTILE_SUB_ROLE, LEGACY_LIGHT_HEAL_SUB_ROLE}
)

_DAMAGE_ROLE_ALIASES = frozenset({"damage", "dps"})
_SUPPORT_ROLE_ALIASES = frozenset({"support", "heal", "healer"})

# Registration uses the short codes tank/dps/support, while the canonical
# PlayerSubRole catalog (and HeroClass) uses tank/damage/support. These maps
# bridge the two so the catalog can stay the single source of truth.
REGISTRATION_ROLE_CODES: tuple[str, ...] = ("tank", "dps", "support")
REGISTRATION_TO_CANONICAL: dict[str, str] = {
    "tank": "tank",
    "dps": "damage",
    "support": "support",
}
_CANONICAL_TO_REGISTRATION: dict[str, str] = {
    "tank": "tank",
    "damage": "dps",
    "support": "support",
}


def normalize_role(role: Any) -> str | None:
    if role is None:
        return None

    if isinstance(role, Enum):
        role = role.value

    value = str(role).strip().lower()
    if value in _DAMAGE_ROLE_ALIASES:
        return "damage"
    if value in _SUPPORT_ROLE_ALIASES:
        return "support"
    if value == "tank":
        return "tank"

    return value or None


def normalize_sub_role(sub_role: str | None) -> str | None:
    if sub_role is None:
        return None

    normalized = re.sub(r"\s+", "_", sub_role.strip().lower())
    return normalized or None


def legacy_flags_to_sub_role(
    role: Any,
    *,
    primary: bool | None,
    secondary: bool | None,
) -> str | None:
    role_key = normalize_role(role)
    is_primary = bool(primary)
    is_secondary = bool(secondary)

    if is_primary == is_secondary:
        return None

    if role_key == "damage":
        return LEGACY_HITSCAN_SUB_ROLE if is_primary else LEGACY_PROJECTILE_SUB_ROLE
    if role_key == "support":
        return LEGACY_MAIN_HEAL_SUB_ROLE if is_primary else LEGACY_LIGHT_HEAL_SUB_ROLE

    return None


def sub_role_to_legacy_flags(role: Any, sub_role: str | None) -> tuple[bool, bool]:
    role_key = normalize_role(role)
    sub_role_key = normalize_sub_role(sub_role)

    if role_key == "damage":
        if sub_role_key == LEGACY_HITSCAN_SUB_ROLE:
            return (True, False)
        if sub_role_key == LEGACY_PROJECTILE_SUB_ROLE:
            return (False, True)

    if role_key == "support":
        if sub_role_key == LEGACY_MAIN_HEAL_SUB_ROLE:
            return (True, False)
        if sub_role_key == LEGACY_LIGHT_HEAL_SUB_ROLE:
            return (False, True)

    return (False, False)


def resolve_sub_role(
    role: Any,
    *,
    sub_role: str | None,
    primary: bool | None,
    secondary: bool | None,
) -> str | None:
    return normalize_sub_role(sub_role) or legacy_flags_to_sub_role(
        role,
        primary=primary,
        secondary=secondary,
    )


def registration_to_canonical_role(role: Any) -> str | None:
    """Map a registration role code (tank/dps/support) to its canonical name."""
    return normalize_role(role)


def canonical_to_registration_role(role: Any) -> str | None:
    """Map a canonical role (tank/damage/support) to a registration code."""
    canonical = normalize_role(role)
    if canonical is None:
        return None
    return _CANONICAL_TO_REGISTRATION.get(canonical)


class SubRoleRow(Protocol):
    """Duck-typed PlayerSubRole row used to build the catalog."""

    role: str
    slug: str
    label: str


def build_subrole_catalog(
    rows: Iterable[SubRoleRow],
) -> dict[str, list[dict[str, str]]]:
    """Group catalog rows by registration role code, preserving input order.

    Returns ``{reg_code: [{"slug": ..., "label": ...}]}`` for every registration
    role code, so the frontend always receives a stable shape. Callers should
    pass rows already sorted (role, sort_order, label).
    """
    catalog: dict[str, list[dict[str, str]]] = {
        code: [] for code in REGISTRATION_ROLE_CODES
    }
    for row in rows:
        reg_code = canonical_to_registration_role(getattr(row, "role", None))
        if reg_code is None or reg_code not in catalog:
            continue
        slug = normalize_sub_role(getattr(row, "slug", None))
        if slug is None:
            continue
        label = getattr(row, "label", None) or slug
        catalog[reg_code].append({"slug": slug, "label": str(label)})
    return catalog
