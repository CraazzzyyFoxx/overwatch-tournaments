import type {
  DivisionGrid,
  DivisionGridVersion,
  DivisionTier,
} from "@/types/workspace.types";

type DivisionGridLike = Pick<DivisionGrid, "tiers"> | Pick<DivisionGridVersion, "tiers">;

const DEFAULT_DIVISION_ICON_BASE =
  "https://minio.craazzzyyfoxx.me/aqt/assets/divisions";

const DEFAULT_DIVISION_GRID_TIERS: DivisionTier[] = (() => {
  const divisions = ["champion", "grandmaster", "master", "diamond", "platinum", "gold", "silver", "bronze"];
  const bases: Record<string, number> = {
    bronze: 1000,
    silver: 1500,
    gold: 2000,
    platinum: 2500,
    diamond: 3000,
    master: 3500,
    grandmaster: 4000,
    champion: 4500,
  };
  
  const tiers: DivisionTier[] = [];
  let sort_order = 0;
  let number = 1;
  
  for (const div of divisions) {
    const base = bases[div];
    for (let tier_num = 1; tier_num <= 5; tier_num++) {
      const slug = `${div}-${tier_num}`;
      const name = `${div.charAt(0).toUpperCase() + div.slice(1)} ${tier_num}`;
      const offset = (5 - tier_num) * 100;
      const rank_min = base + offset;
      const rank_max = (div === "champion" && tier_num === 1) ? null : rank_min + 99;
      const icon_url = `${DEFAULT_DIVISION_ICON_BASE}/${slug}.png`;
      
      tiers.push({
        slug,
        number,
        name,
        sort_order,
        rank_min,
        rank_max,
        icon_url,
      });
      sort_order++;
      number++;
    }
  }
  
  return tiers.sort((left, right) => right.rank_min - left.rank_min);
})();

export const DEFAULT_DIVISION_GRID: DivisionGrid = {
  tiers: DEFAULT_DIVISION_GRID_TIERS,
};

export function getDefaultDivisionGrid(): DivisionGrid {
  return DEFAULT_DIVISION_GRID;
}

export function sortTiersAscending(grid: DivisionGridLike): DivisionTier[] {
  return [...grid.tiers].sort((left, right) => left.rank_min - right.rank_min);
}

export function sortTiersDescending(grid: DivisionGridLike): DivisionTier[] {
  return [...grid.tiers].sort((left, right) => right.rank_min - left.rank_min);
}

export function getTierByDivision(
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

export function resolveRankFromDivision(
  grid: DivisionGridLike,
  division: number | null | undefined,
): number | null {
  const tier = getTierByDivision(grid, division);
  if (!tier) {
    return null;
  }

  if (tier.rank_max === null) {
    return tier.rank_min;
  }

  return Math.floor((tier.rank_min + tier.rank_max) / 2);
}

export function resolveExactRankFromDivision(
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

  return `${DEFAULT_DIVISION_ICON_BASE}/bronze-5.png`;
}
