from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any, Protocol

from shared.core.enums import HeroClass

# Registration, the PlayerSubRole catalog and the roster shape all speak one
# vocabulary: tank/damage/support (``HeroClass.slot_code`` == ``HeroClass.name``).
# Registration used to spell damage as ``dps``; migration ``roledps01`` retired
# that. ``REGISTRATION_TO_CANONICAL`` is therefore an identity map now, kept
# because callers use it as a *validated* lookup -- ``.get()`` answers None for a
# role that is not one of the three, which a bare string would not.
_REGISTRATION_ROLES: tuple[HeroClass, ...] = (HeroClass.tank, HeroClass.damage, HeroClass.support)
REGISTRATION_ROLE_CODES: tuple[str, ...] = tuple(role.slot_code for role in _REGISTRATION_ROLES)
REGISTRATION_TO_CANONICAL: dict[str, str] = {role.slot_code: role.name for role in _REGISTRATION_ROLES}


def normalize_role(role: Any) -> str | None:
    if role is None:
        return None

    parsed = HeroClass.parse(role)
    if parsed is not None:
        return parsed.name

    value = str(role).strip().lower()
    return value or None


def normalize_sub_role(sub_role: str | None) -> str | None:
    if sub_role is None:
        return None

    normalized = re.sub(r"\s+", "_", sub_role.strip().lower())
    return normalized or None


def catalog_slugs(
    catalog: dict[str, Iterable[Any]] | None,
    role: str | None = None,
) -> set[str] | None:
    """Allowed sub-role slugs from a workspace catalog.

    ``None`` catalog means the caller has nothing to enforce (skip). An empty
    catalog means no slugs are allowed. ``role`` None/flex unions every role;
    a registration code (tank/damage/support) returns that role only.
    """
    if catalog is None:
        return None
    codes: Iterable[str] = (role,) if role and role != "flex" else catalog.keys()
    slugs: set[str] = set()
    for code in codes:
        for entry in catalog.get(code, []) or []:
            raw = entry.get("slug") if isinstance(entry, dict) else getattr(entry, "slug", None)
            slug = normalize_sub_role(raw if isinstance(raw, str) else None)
            if slug:
                slugs.add(slug)
    return slugs


def registration_to_canonical_role(role: Any) -> str | None:
    """Normalize any role spelling to its canonical code, ``None`` if unrecognised.

    Registration and the catalog share one vocabulary, so this no longer
    translates; it validates. ``flex`` passes through -- a registration may be
    role-less even though the sub-role catalog has no flex rows.
    """
    return normalize_role(role)


def canonical_to_registration_role(role: Any) -> str | None:
    """Same, narrowed to the three roles a registration can name.

    ``None`` for ``flex`` and for anything unrecognised, which is what the
    sub-role catalog lookups need: flex has no catalog to index.
    """
    canonical = normalize_role(role)
    return canonical if canonical in REGISTRATION_ROLE_CODES else None


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
    catalog: dict[str, list[dict[str, str]]] = {code: [] for code in REGISTRATION_ROLE_CODES}
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
