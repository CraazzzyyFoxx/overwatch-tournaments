"""THE Overwatch competitive ladder — the one place its shape is written down.

Everything about the ladder that is a *fact* rather than a derivation lives in
:data:`LADDER`: the divisions, their order, the SR each one starts at, and the
two names each division answers to. Every consumer derives from it:

- :mod:`shared.division_grid` builds ``DEFAULT_GRID`` (the 45-tier fallback grid
  every service resolves ranks against) out of :func:`iter_tiers`;
- ``tournament-service``'s ``get_default_ow2_tiers_write`` projects that grid
  into its write DTO — it does not re-derive anything;
- ``parser-service``'s ``overwatch_rank.mapping`` takes its native
  division → base table from :func:`ow_division_bases`;
- the frontend mirrors this table in ``frontend/src/lib/ow-ladder.ts``, pinned
  by the parity test described there (it cannot import Python, and the default
  grid has to be available synchronously during SSR).

Adding or re-anchoring a division means editing :data:`LADDER` and nothing else
on the Python side.

Two names, deliberately
-----------------------
The top division is ``champion`` on the division-grid side (tier slugs, tier
names, icon filenames) and ``ultimate`` on the OverFast wire. They never meet at
runtime — the OverFast name is only ever a dict key that yields an integer
``rank_value``, and the bridge back to a grid tier
(:meth:`shared.division_grid.DivisionGrid.resolve_division_from_ow_rank`) is
purely numeric. Unifying them would be a data migration over stored tier slugs
and stored snapshot divisions for no behavioural gain, so one record simply
carries both.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from shared.core.enums import RankDivision

__all__ = (
    "DIVISION_ICON_BASE",
    "LADDER",
    "LadderDivision",
    "TIERS_PER_DIVISION",
    "TIER_SPAN",
    "LadderTier",
    "iter_tiers",
    "ow_division_bases",
    "tier_rank_min",
)

#: Sub-tiers per division, tier 1 the top and tier ``TIERS_PER_DIVISION`` the bottom.
TIERS_PER_DIVISION = 5
#: SR span of a single sub-tier; a division therefore spans ``5 * 100 = 500``.
TIER_SPAN = 100

#: Site-relative path of the default OW2 rank icons (``bronze-5.png`` … ``champion-1.png``).
#: Served from ``frontend/public/divisions``. A full CDN URL used to live here
#: (``static.nl.craazzzyyfoxx.me``); that host is gone, and baking an S3 public
#: URL into the ladder made every deployment depend on one bucket. Workspace
#: grids still store their own absolute ``icon_url``s.
DIVISION_ICON_BASE = "/divisions"


@dataclass(frozen=True)
class LadderDivision:
    """One division of the ladder.

    ``slug`` is the division-grid identity: tier slugs (``f"{slug}-{tier}"``),
    tier display names and icon filenames are all built from it, and existing DB
    rows carry those strings. ``ow_division`` is the OverFast wire value the
    parser receives. ``base`` is the ``rank_value`` of the division's BOTTOM
    tier. ``open_top`` marks the single division whose tier 1 has no upper bound
    — the ladder has no ceiling above it.
    """

    slug: str
    ow_division: RankDivision
    base: int
    open_top: bool = False


#: The ladder, top division first.
#:
#: Nine 500-wide divisions anchored at Bronze 5 = 500, so the ladder runs
#: 500..4899 with Champion 1 open-ended above 4900. Emerald holds the 2500 band
#: platinum used to, which is why diamond and above kept their pre-emerald
#: anchors when Emerald was introduced.
LADDER: tuple[LadderDivision, ...] = (
    LadderDivision("champion", RankDivision.ultimate, 4500, open_top=True),
    LadderDivision("grandmaster", RankDivision.grandmaster, 4000),
    LadderDivision("master", RankDivision.master, 3500),
    LadderDivision("diamond", RankDivision.diamond, 3000),
    LadderDivision("emerald", RankDivision.emerald, 2500),
    LadderDivision("platinum", RankDivision.platinum, 2000),
    LadderDivision("gold", RankDivision.gold, 1500),
    LadderDivision("silver", RankDivision.silver, 1000),
    LadderDivision("bronze", RankDivision.bronze, 500),
)


@dataclass(frozen=True)
class LadderTier:
    """A single sub-tier, resolved to everything a grid tier needs.

    ``number`` is 1-based from the top of the ladder, matching the division
    numbering the whole codebase uses (1 = Champion 1, 45 = Bronze 5).
    """

    number: int
    division: LadderDivision
    tier: int
    slug: str
    name: str
    rank_min: int
    rank_max: int | None
    icon_url: str


def tier_rank_min(base: int, tier: int) -> int:
    """``rank_value`` at the bottom of ``tier`` within a division based at ``base``."""
    return base + (TIERS_PER_DIVISION - tier) * TIER_SPAN


def iter_tiers() -> Iterator[LadderTier]:
    """Every sub-tier of the ladder, top (Champion 1) to bottom (Bronze 5)."""
    number = 1
    for division in LADDER:
        for tier in range(1, TIERS_PER_DIVISION + 1):
            rank_min = tier_rank_min(division.base, tier)
            slug = f"{division.slug}-{tier}"
            yield LadderTier(
                number=number,
                division=division,
                tier=tier,
                slug=slug,
                name=f"{division.slug.capitalize()} {tier}",
                rank_min=rank_min,
                rank_max=None if division.open_top and tier == 1 else rank_min + TIER_SPAN - 1,
                icon_url=f"{DIVISION_ICON_BASE}/{slug}.png",
            )
            number += 1


def ow_division_bases() -> Mapping[str, int]:
    """Native OverFast division → ``rank_value`` of its bottom tier."""
    return MappingProxyType({division.ow_division.value: division.base for division in LADDER})
