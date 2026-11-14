"""Challenge-code fallback for providers with no API (Boosty).

The author publishes a secret code inside a post restricted to a subscription
level; redeeming the code proves the patron can read that level. Only the
SHA-256 digest is ever persisted -- the same discipline the OAuth state applies
to ``csrf``/``guard_hash``.

This proves ACCESS TO A LEVEL, not identity: a code is shareable. Rotate codes
per tournament.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

__all__ = ("CodeTier", "has_live_code", "hash_code", "match_code", "parse_code_tiers")


@dataclass(frozen=True, slots=True)
class CodeTier:
    code_sha256: str
    tier_rank: int
    tier_label: str
    expires_at: datetime | None


def _normalize(code: str | None) -> str:
    return (code or "").strip().casefold()


def hash_code(code: str | None) -> str:
    """SHA-256 hex of the normalized code. Casing/whitespace are noise."""
    return hashlib.sha256(_normalize(code).encode("utf-8")).hexdigest()


def coerce_expiry(value: object) -> datetime | None:
    """Best-effort ``expires_at`` -> aware ``datetime``.

    ``config_json`` is JSON, so an expiry round-trips as an ISO **string**, not a
    ``datetime``; comparing that against ``now`` would raise ``TypeError``. A
    naive datetime (no tzinfo) would raise for the same reason, so it is assumed
    UTC. An unparseable value yields ``None`` -- "no expiry" -- because silently
    expiring a live code, or raising mid-check-in, are both worse than ignoring a
    malformed date.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def match_code(submitted: str | None, tiers: Sequence[CodeTier], *, now: datetime) -> CodeTier | None:
    """Highest live tier whose code matches ``submitted``, or ``None``.

    Highest wins so a duplicated code in config cannot silently downgrade a patron.
    """
    normalized = _normalize(submitted)
    if not normalized:
        return None
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    live = []
    for tier in tiers:
        if tier.code_sha256 != digest:
            continue
        expires_at = coerce_expiry(tier.expires_at)
        if expires_at is None or expires_at > now:
            live.append(tier)
    if not live:
        return None
    return max(live, key=lambda tier: tier.tier_rank)


def parse_code_tiers(config: dict[str, Any] | None) -> tuple[CodeTier, ...]:
    """Read ``codes`` out of a provider config blob, skipping malformed rows."""
    parsed: list[CodeTier] = []
    for row in (config or {}).get("codes") or []:
        digest = str(row.get("code_sha256") or "").strip()
        if not digest:
            continue
        try:
            tier_rank = int(row.get("tier_rank"))
        except TypeError, ValueError:
            continue
        parsed.append(
            CodeTier(
                code_sha256=digest,
                tier_rank=tier_rank,
                tier_label=str(row.get("tier_label") or ""),
                expires_at=coerce_expiry(row.get("expires_at")),
            )
        )
    return tuple(parsed)


def has_live_code(config: dict[str, Any] | None, *, now: datetime) -> bool:
    """Whether ANY configured code is still redeemable.

    Not the same question as ``match_code``, which needs a submitted string. This
    answers "would pasting anything here ever work", which is what decides whether
    the UI offers the field and whether the registration gate defers a refusal.
    """
    return any(tier.expires_at is None or tier.expires_at > now for tier in parse_code_tiers(config))
