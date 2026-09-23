import { DIVISION_ICON_BASE, LADDER_TIERS } from "@/lib/divisions/ow-ladder";
import type {
  DivisionGrid,
  DivisionGridVersion,
  DivisionTier,
} from "@/types/workspace.types";

type DivisionGridLike = Pick<DivisionGrid, "tiers"> | Pick<DivisionGridVersion, "tiers">;

/**
 * The Overwatch ladder as a grid, derived from `@/lib/divisions/ow-ladder`.
 *
 * Tiers come out top-first, which for this grid is already descending by
 * `rank_min` — the order a stored grid arrives in — so both paths hand callers
 * the same ordering. `sort_order` is the tier's position, which here equals
 * `number - 1`.
 */
const OW_LADDER_TIERS: DivisionTier[] = LADDER_TIERS.map((tier, index) => ({
  slug: tier.slug,
  number: tier.number,
  name: tier.name,
  sort_order: index,
  rank_min: tier.rank_min,
  rank_max: tier.rank_max,
  icon_url: tier.icon_url,
}));

/**
 * The OW ladder itself — Bronze 5 = 500 … Champion 1 = 4900+.
 *
 * Use this wherever the numbers on hand are on the **OW/SR scale**: OverFast
 * snapshot `rank_value`s, and the global `parser.rank_mapping` cells (whose
 * values the backend re-resolves per workspace at autofill time, so they must
 * stay OW-scale). Reaching for a workspace grid there is wrong, not more
 * correct: an SR of 3200 is Diamond 3 in OW terms no matter what a workspace
 * calls its 14th division.
 *
 * Same object as {@link DEFAULT_DIVISION_GRID}, deliberately a second name: that
 * one means "we could not get the real grid", and reading a fallback where an
 * absolute reference was meant invites swapping in `useDivisionGrid()` and
 * silently corrupting OW-scale values.
 */
export const OW_REFERENCE_GRID: DivisionGrid = {
  tiers: OW_LADDER_TIERS,
};

/**
 * Fallback grid for when the workspace's real one is not available yet.
 *
 * That happens on every server render and every first client render: the
 * workspace store persists only `currentWorkspaceId` and fetches the workspace
 * (which carries the grid) in a client effect. Prefer `useDivisionGrid()`, which
 * falls back to this on its own.
 */
export const DEFAULT_DIVISION_GRID: DivisionGrid = OW_REFERENCE_GRID;

export function getDefaultDivisionGrid(): DivisionGrid {
  return DEFAULT_DIVISION_GRID;
}

export function sortTiersAscending(grid: DivisionGridLike): DivisionTier[] {
  return [...grid.tiers].sort((left, right) => left.rank_min - right.rank_min);
}

export function sortTiersDescending(grid: DivisionGridLike): DivisionTier[] {
  return [...grid.tiers].sort((left, right) => right.rank_min - left.rank_min);
}

function getTierByDivision(
  grid: DivisionGridLike,
  division: number | null | undefined,
): DivisionTier | null {
  if (division == null) {
    return null;
  }

  return grid.tiers.find((tier) => tier.number === division) ?? null;
}

export function getTierForRank(
  grid: DivisionGridLike,
  rank: number | null | undefined,
): DivisionTier | null {
  if (rank == null) {
    return null;
  }

  for (const tier of grid.tiers) {
    if (tier.rank_max === null) {
      if (rank >= tier.rank_min) {
        return tier;
      }
      continue;
    }

    if (rank >= tier.rank_min && rank <= tier.rank_max) {
      return tier;
    }
  }

  return grid.tiers.at(-1) ?? null;
}

export function resolveDivisionFromRank(
  grid: DivisionGridLike,
  rank: number | null | undefined,
): number | null {
  return getTierForRank(grid, rank)?.number ?? null;
}

/**
 * The `rank_value` representing a division — its tier floor. A division is a band, so
 * the floor is the canonical point (matches the backend `resolve_rank_for_division`, the
 * grid normalizer and the rank slider). A band midpoint produced off-grid values such as
 * 4449 for Grandmaster 1 (4400..4499).
 */
export function resolveRankFromDivision(
  grid: DivisionGridLike,
  division: number | null | undefined,
): number | null {
  return getTierByDivision(grid, division)?.rank_min ?? null;
}

export function getDivisionOptions(grid: DivisionGridLike): number[] {
  return [...grid.tiers].sort((left, right) => left.number - right.number).map((tier) => tier.number);
}

export function clampDivisionToGrid(
  grid: DivisionGridLike,
  division: number | null | undefined,
): number | undefined {
  if (division == null) {
    return undefined;
  }

  const divisionOptions = getDivisionOptions(grid);
  if (divisionOptions.length === 0) {
    return undefined;
  }

  const minDivision = divisionOptions[0];
  const maxDivision = divisionOptions.at(-1) ?? minDivision;
  return Math.min(Math.max(division, minDivision), maxDivision);
}

export function getDivisionLabel(
  grid: DivisionGridLike,
  division: number | null | undefined,
): string | null {
  if (division == null) {
    return null;
  }

  return getTierByDivision(grid, division)?.name ?? `Division ${division}`;
}

export function getDivisionIconSrc(
  grid: DivisionGridLike,
  division: number | null | undefined,
): string | null {
  if (division == null) {
    return null;
  }

  const tier = getTierByDivision(grid, division);
  if (tier) {
    return tier.icon_url;
  }

  // Fallback to default grid lookup
  const defaultTier = getTierByDivision(DEFAULT_DIVISION_GRID, division);
  if (defaultTier) {
    return defaultTier.icon_url;
  }

  return `${DIVISION_ICON_BASE}/bronze-5.png`;
}
