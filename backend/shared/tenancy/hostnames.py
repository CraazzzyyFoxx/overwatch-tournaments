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
    "is_platform_host",
    "normalize_custom_domain",
)

PLATFORM_ZONE = "owt.craazzzyyfoxx.me"

RESERVED_SUBDOMAINS = frozenset({"www", "api", "auth", "admin", "app", "assets", "static", "cdn", "mail", "ws"})

_LABEL_RE = re.compile(r"^[a-z0-9-]+$")

_DOMAIN_RE = re.compile(r"^(?=.{1,253}$)(?!-)[a-z0-9-]{1,63}(?:\.(?!-)[a-z0-9-]{1,63})+$")


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


def is_platform_host(host: str) -> bool:
    """Check if host is the platform zone apex or a subdomain under it."""
    h = host.strip().lower().split(":", 1)[0]
    return h == PLATFORM_ZONE or h.endswith("." + PLATFORM_ZONE)


def normalize_custom_domain(domain: str) -> str:
    """Normalize and validate a custom domain.

    - Lowercase, strip whitespace, strip trailing dot and port.
    - Must be a valid multi-label FQDN (at least one dot).
    - Rejects empty, non-FQDN, and any host under the platform zone.

    Raises ValueError if invalid.
    """
    d = domain.strip().lower().rstrip(".").split(":", 1)[0]
    if not d or "." not in d or not _DOMAIN_RE.fullmatch(d):
        raise ValueError("Invalid custom domain")
    if is_platform_host(d):
        raise ValueError("Custom domain must not be under the platform zone")
    return d
