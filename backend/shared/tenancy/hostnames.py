"""Platform-zone hostname helpers for host->workspace resolution.

Phase 1 handles subdomains under the platform zone. Custom domains (Phase 2)
match a separate column and are resolved elsewhere.
"""

from __future__ import annotations

import re

__all__ = (
    "PLATFORM_ZONE",
    "RESERVED_SUBDOMAINS",
    "validate_subdomain_label",
    "subdomain_from_host",
)

PLATFORM_ZONE = "owt.craazzzyyfoxx.me"

RESERVED_SUBDOMAINS = frozenset({"www", "api", "auth", "admin", "app", "assets", "static", "cdn", "mail", "ws"})

_LABEL_RE = re.compile(r"^[a-z0-9-]+$")


def validate_subdomain_label(label: str) -> str:
    normalized = label.strip().lower()
    if not (1 <= len(normalized) <= 63):
        raise ValueError("Subdomain must be 1-63 characters")
    if not _LABEL_RE.fullmatch(normalized):
        raise ValueError("Subdomain may contain only a-z, 0-9 and hyphen")
    if normalized.startswith("-") or normalized.endswith("-"):
        raise ValueError("Subdomain may not start or end with a hyphen")
    if normalized in RESERVED_SUBDOMAINS:
        raise ValueError(f"Subdomain '{normalized}' is reserved")
    return normalized


def subdomain_from_host(host: str) -> str | None:
    if not host:
        return None
    hostname = host.strip().lower().split(":", 1)[0]  # drop port
    suffix = "." + PLATFORM_ZONE
    if not hostname.endswith(suffix):
        return None
    label = hostname[: -len(suffix)]
    if not label or "." in label:  # apex has empty label; multi-segment rejected
        return None
    try:
        return validate_subdomain_label(label)
    except ValueError:
        return None
