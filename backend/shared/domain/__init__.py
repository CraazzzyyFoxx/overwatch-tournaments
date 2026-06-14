"""Domain-level business rules shared by backend services."""

from .player_sub_roles import (
    LEGACY_PRIMARY_SUB_ROLES,
    LEGACY_SECONDARY_SUB_ROLES,
    REGISTRATION_ROLE_CODES,
    REGISTRATION_TO_CANONICAL,
    build_subrole_catalog,
    canonical_to_registration_role,
    legacy_flags_to_sub_role,
    normalize_role,
    normalize_sub_role,
    registration_to_canonical_role,
    resolve_sub_role,
    sub_role_to_legacy_flags,
)

__all__ = (
    "LEGACY_PRIMARY_SUB_ROLES",
    "LEGACY_SECONDARY_SUB_ROLES",
    "REGISTRATION_ROLE_CODES",
    "REGISTRATION_TO_CANONICAL",
    "build_subrole_catalog",
    "canonical_to_registration_role",
    "legacy_flags_to_sub_role",
    "normalize_role",
    "normalize_sub_role",
    "registration_to_canonical_role",
    "resolve_sub_role",
    "sub_role_to_legacy_flags",
)
