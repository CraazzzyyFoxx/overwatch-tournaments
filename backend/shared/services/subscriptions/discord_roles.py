"""Map a Discord member's role ids to a subscription tier.

Boosty's own Discord integration assigns a role per subscription level. This
module is the pure half of the ``discord_role`` provider: no Discord client, no
DB, so the mapping rules are unit-testable in isolation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = ("RoleTier", "parse_role_tiers", "resolve_role_tier")


@dataclass(frozen=True, slots=True)
class RoleTier:
    """One configured ``discord role -> subscription tier`` mapping.

    ``role_id`` is a Discord snowflake and is kept as a STRING: snowflakes exceed
    2**53 and must never survive a float round-trip. Callers may pass ints (that
    is what ``discord.py`` exposes as ``Role.id``); both sides are stringified
    before comparison.
    """

    role_id: str
    tier_rank: int
    tier_label: str


def resolve_role_tier(role_ids: Iterable[str | int], tiers: Sequence[RoleTier]) -> RoleTier | None:
    """Highest-ranked configured tier among ``role_ids``, or ``None``.

    Highest wins because Boosty leaves the lower-level role attached when a
    patron upgrades, so a member legitimately holds several mapped roles.
    """
    held = {str(role_id) for role_id in role_ids}
    matches = [tier for tier in tiers if tier.role_id in held]
    if not matches:
        return None
    return max(matches, key=lambda tier: tier.tier_rank)


def parse_role_tiers(config: dict[str, Any] | None) -> tuple[RoleTier, ...]:
    """Read ``role_tiers`` out of a provider config blob, skipping malformed rows.

    Malformed rows are dropped rather than raised on: a single bad config row must
    not break resolution for everybody.
    """
    parsed: list[RoleTier] = []
    for row in (config or {}).get("role_tiers") or []:
        role_id = str(row.get("role_id") or "").strip()
        if not role_id:
            continue
        try:
            tier_rank = int(row.get("tier_rank"))
        except TypeError, ValueError:
            continue
        parsed.append(
            RoleTier(
                role_id=role_id,
                tier_rank=tier_rank,
                tier_label=str(row.get("tier_label") or ""),
            )
        )
    return tuple(parsed)
