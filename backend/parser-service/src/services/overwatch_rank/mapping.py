"""Native OverFast division+tier -> integer rank_value mapping.

The default is an Overwatch 2 SR-aligned scale: each division spans 500 points
and each of its 5 tiers spans 100, with tier 5 the bottom and tier 1 the top of
a division. The mapping is configurable at runtime via the ``parser.rank_mapping``
settings key — admin-provided entries override individual cells of this default.
The native ``division``/``tier`` are always stored on the snapshot regardless, so
a mapping miss never loses source data.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import enums
from shared.services import settings_provider

DEFAULT_MAPPING_VERSION = "ow2-default-v1"

#: Lower bound (tier 5) rank_value per native division.
DEFAULT_OW2_DIVISION_BASE: Mapping[str, int] = MappingProxyType(
    {
        enums.RankDivision.bronze.value: 1000,
        enums.RankDivision.silver.value: 1500,
        enums.RankDivision.gold.value: 2000,
        enums.RankDivision.platinum.value: 2500,
        enums.RankDivision.diamond.value: 3000,
        enums.RankDivision.master.value: 3500,
        enums.RankDivision.grandmaster.value: 4000,
        enums.RankDivision.ultimate.value: 4500,
    }
)

# Lookup key: (division_lowercase, tier) -> rank_value.
RankLookup = dict[tuple[str, int], int]


def _tier_offset(tier: int) -> int:
    # Tier 5 = bottom of division (offset 0), tier 1 = top (offset 400).
    return (5 - tier) * 100


def build_default_lookup() -> RankLookup:
    lookup: RankLookup = {}
    for division, base in DEFAULT_OW2_DIVISION_BASE.items():
        for tier in range(1, 6):
            lookup[(division, tier)] = base + _tier_offset(tier)
    return lookup


def map_division_tier_to_rank_value(
    division: str | None,
    tier: int | None,
    lookup: RankLookup,
) -> int | None:
    """Resolve a native division+tier to an integer rank_value, or ``None``."""
    if not division or tier is None:
        return None
    return lookup.get((division.lower(), int(tier)))


async def get_rank_mapping(session: AsyncSession) -> tuple[RankLookup, str]:
    """Load the effective division+tier -> rank_value lookup and its version.

    Starts from the built-in default and overlays any admin-configured entries
    from ``parser.rank_mapping``. Returns ``(lookup, mapping_version)``; the
    version is recorded on each snapshot so a later mapping change is auditable.
    """
    config = await settings_provider.get_rank_mapping_config(session)
    lookup = build_default_lookup()
    for entry in config.entries:
        lookup[(entry.division.lower(), entry.tier)] = entry.rank_value
    version = config.version or DEFAULT_MAPPING_VERSION
    return lookup, version
