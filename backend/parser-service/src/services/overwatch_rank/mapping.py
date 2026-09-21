"""Effective native OverFast division+tier -> integer rank_value mapping.

The default table (:func:`build_default_lookup`, in
``src.domain.overwatch_rank``) is derived from :data:`shared.domain.ow_ladder.LADDER`
— the one place the ladder's shape is written down — so it cannot drift from
the division grid every service resolves ranks against. The mapping is
configurable at runtime via the ``parser.rank_mapping`` settings key:
admin-provided entries override individual cells of the default.

The native ``division``/``tier`` are always stored on the snapshot regardless,
so a mapping miss never loses source data, and a rebase of the ladder (see
``DEFAULT_RANK_MAPPING_VERSION``) can always be backfilled from them.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.schemas.settings import DEFAULT_RANK_MAPPING_VERSION
from shared.services.settings_provider import settings_provider
from src.domain.overwatch_rank import RankLookup, build_default_lookup, map_division_tier_to_rank_value

# ``build_default_lookup``/``map_division_tier_to_rank_value`` now live in
# ``src.domain.overwatch_rank`` (pure logic); re-imported here so this module
# keeps resolving them for existing callers/tests
# (``mapping.build_default_lookup(...)``).
__all__ = ("RankLookup", "build_default_lookup", "map_division_tier_to_rank_value", "get_rank_mapping")


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
    version = config.version or DEFAULT_RANK_MAPPING_VERSION
    return lookup, version
