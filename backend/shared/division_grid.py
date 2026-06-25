from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import sqlalchemy as sa

from shared.domain import division_rank

if TYPE_CHECKING:
    from shared.models.division_grid import DivisionGridVersion


@dataclass(frozen=True)
class DivisionTier:
    id: int | None
    slug: str | None
    number: int
    name: str
    rank_min: int
    rank_max: int | None
    icon_url: str
    ow_rank_min: int | None = None
    ow_rank_max: int | None = None


@dataclass(frozen=True)
class DivisionGrid:
    version_id: int | None
    tiers: tuple[DivisionTier, ...]

    def resolve_division(self, rank: int) -> DivisionTier:
        return division_rank.resolve_tier_for_rank(self, rank)  # type: ignore[return-value]

    def resolve_division_number(self, rank: int) -> int:
        return division_rank.resolve_division_for_rank(self, rank)

    def resolve_rank_from_division(self, division_number: int) -> int | None:
        return division_rank.resolve_rank_for_division(self, division_number)

    def resolve_division_from_ow_rank(self, ow_rank: int) -> DivisionTier | None:
        """Find the tier whose ow_rank_min/ow_rank_max range contains ow_rank.

        The pair is treated as an unordered interval: admins enter the top
        divisions high→low (e.g. "Ultimate 1 → Ultimate 3"), which stores
        ow_rank_min > ow_rank_max. Comparing against ``min``/``max`` of the pair
        keeps those tiers matching instead of silently dropping the highest
        ranks. Returns None when no tier has OW rank mapping configured or the
        rank falls outside all configured ranges.
        """
        for tier in self.tiers:
            if tier.ow_rank_min is None or tier.ow_rank_max is None:
                continue
            low = min(tier.ow_rank_min, tier.ow_rank_max)
            high = max(tier.ow_rank_min, tier.ow_rank_max)
            if low <= ow_rank <= high:
                return tier
        return None

    @property
    def max_division(self) -> int:
        return max(t.number for t in self.tiers)

    @property
    def min_division(self) -> int:
        return min(t.number for t in self.tiers)

    @staticmethod
    def from_version(version: DivisionGridVersion | None) -> DivisionGrid:
        if version is None or not version.tiers:
            return DEFAULT_GRID

        tiers = []
        for t in version.tiers:
            tiers.append(
                DivisionTier(
                    id=t.id,
                    slug=t.slug,
                    number=int(t.number),
                    name=str(t.name),
                    rank_min=int(t.rank_min),
                    rank_max=int(t.rank_max) if t.rank_max is not None else None,
                    icon_url=str(t.icon_url),
                    ow_rank_min=int(t.ow_rank_min) if getattr(t, "ow_rank_min", None) is not None else None,
                    ow_rank_max=int(t.ow_rank_max) if getattr(t, "ow_rank_max", None) is not None else None,
                )
            )

        tiers.sort(key=lambda tier: tier.rank_min, reverse=True)
        return DivisionGrid(version_id=version.id, tiers=tuple(tiers))

    def to_json(self) -> dict[str, Any]:
        return {
            "tiers": [
                {
                    "id": t.id,
                    "slug": t.slug,
                    "number": t.number,
                    "name": t.name,
                    "rank_min": t.rank_min,
                    "rank_max": t.rank_max,
                    "icon_url": t.icon_url,
                }
                for t in self.tiers
            ]
        }


def _build_default_grid() -> DivisionGrid:
    divisions = ["champion", "grandmaster", "master", "diamond", "platinum", "gold", "silver", "bronze"]
    bases = {
        "bronze": 1000,
        "silver": 1500,
        "gold": 2000,
        "platinum": 2500,
        "diamond": 3000,
        "master": 3500,
        "grandmaster": 4000,
        "champion": 4500,
    }

    tiers = []
    number = 1

    for div in divisions:
        base = bases[div]
        for tier_num in range(1, 6):
            slug = f"{div}-{tier_num}"
            name = f"{div.capitalize()} {tier_num}"
            offset = (5 - tier_num) * 100
            rank_min = base + offset

            if div == "champion" and tier_num == 1:
                rank_max = None
            else:
                rank_max = rank_min + 99

            icon_url = f"https://minio.craazzzyyfoxx.me/aqt/assets/divisions/{slug}.png"

            tiers.append(
                DivisionTier(
                    id=None,
                    slug=slug,
                    number=number,
                    name=name,
                    rank_min=rank_min,
                    rank_max=rank_max,
                    icon_url=icon_url,
                )
            )
            number += 1

    tiers.sort(key=lambda t: t.rank_min, reverse=True)
    return DivisionGrid(version_id=None, tiers=tuple(tiers))



DEFAULT_GRID: DivisionGrid = _build_default_grid()


def load_runtime_grid(
    version: DivisionGridVersion | None,
) -> DivisionGrid:
    return DivisionGrid.from_version(version)


def division_case_expr(
    rank_column: sa.ColumnElement[int],
    grid: DivisionGrid,
) -> sa.Case:
    whens: list[tuple[sa.ColumnElement[bool], int]] = []
    for tier in grid.tiers:
        if tier.rank_max is None:
            condition = rank_column >= tier.rank_min
        else:
            condition = sa.and_(rank_column >= tier.rank_min, rank_column <= tier.rank_max)
        whens.append((condition, tier.number))

    return sa.case(*whens, else_=grid.tiers[-1].number)


def division_rank_bounds(
    grid: DivisionGrid,
    div_min: int | None,
    div_max: int | None,
) -> tuple[int | None, int | None] | None:
    """Translate a division-number filter into an equivalent, indexable ``rank`` range.

    ``division_case_expr`` maps ``rank`` to a tier ``number`` monotonically
    (higher rank -> lower number), so ``div_min <= division(rank) <= div_max`` is
    equivalent to a contiguous ``rank`` range. Filtering ``Player.rank`` by that
    range is index-friendly and avoids evaluating the N-branch CASE per row.

    Returns ``(rank_min, rank_max)`` where either bound may be ``None`` (unbounded):
    - ``rank_max is None`` when the selection includes the top, unbounded tier;
    - ``rank_min is None`` when the selection includes the floor tier, which is
      also the CASE's ``else_`` target — ranks below the grid floor map to it, so
      there is no lower bound.

    Returns ``None`` when equivalence cannot be guaranteed (custom/non-contiguous
    grid, floor tier is not the ``else_`` target, or no tier matches). Callers
    must fall back to :func:`division_case_expr` in that case.
    """
    if div_min is None and div_max is None:
        return None

    ordered = sorted(grid.tiers, key=lambda tier: tier.rank_min)
    if not ordered:
        return None

    # Equivalence requires: floor tier (lowest rank) == CASE else_ target,
    # exactly the top tier unbounded, and no gaps/overlaps between tiers.
    floor_tier = ordered[0]
    if grid.tiers[-1].number != floor_tier.number:
        return None
    if ordered[-1].rank_max is not None:
        return None
    for lower, upper in zip(ordered, ordered[1:], strict=False):
        if lower.rank_max is None or lower.rank_max + 1 != upper.rank_min:
            return None

    selected = [
        tier
        for tier in grid.tiers
        if (div_min is None or tier.number >= div_min) and (div_max is None or tier.number <= div_max)
    ]
    if not selected:
        return None

    includes_floor = any(tier.number == floor_tier.number for tier in selected)
    rank_min = None if includes_floor else min(tier.rank_min for tier in selected)
    rank_max = (
        None
        if any(tier.rank_max is None for tier in selected)
        else max(tier.rank_max for tier in selected if tier.rank_max is not None)
    )
    return rank_min, rank_max


def division_filter_predicates(
    rank_column: sa.ColumnElement[int],
    div_min: int | None,
    div_max: int | None,
    grid: DivisionGrid,
) -> list[sa.ColumnElement[bool]]:
    """Predicates for ``div_min <= division(rank) <= div_max``.

    Prefers a plain, index-friendly ``rank`` range (:func:`division_rank_bounds`)
    and falls back to the per-row :func:`division_case_expr` only when the grid
    can't be reduced to a contiguous range. Returns ``[]`` when both bounds are
    ``None`` (no division constraint).
    """
    if div_min is None and div_max is None:
        return []

    bounds = division_rank_bounds(grid, div_min, div_max)
    if bounds is None:
        div_expr = division_case_expr(rank_column, grid)
        preds: list[sa.ColumnElement[bool]] = []
        if div_min is not None:
            preds.append(div_expr >= div_min)
        if div_max is not None:
            preds.append(div_expr <= div_max)
        return preds

    rank_min, rank_max = bounds
    preds = []
    if rank_min is not None:
        preds.append(rank_column >= rank_min)
    if rank_max is not None:
        preds.append(rank_column <= rank_max)
    return preds
