import type { RankMappingEntry } from "@/types/admin.types";

export interface OW2RankOption {
  label: string;
  value: number;
}

export const OW2_DIVISIONS_DESC = [
  "ultimate",
  "grandmaster",
  "master",
  "diamond",
  "platinum",
  "gold",
  "silver",
  "bronze"
] as const;

const DIVISION_BASE: Record<string, number> = {
  bronze: 1000,
  silver: 1500,
  gold: 2000,
  platinum: 2500,
  diamond: 3000,
  master: 3500,
  grandmaster: 4000,
  ultimate: 4500
};

export function defaultRankForCell(division: string, tier: number): number {
  return (DIVISION_BASE[division] ?? 0) + (5 - tier) * 100;
}

/** All OW2 ranks as Select options, sorted highest → lowest (Ultimate 1 … Bronze 5). */
export const OW2_RANK_OPTIONS: OW2RankOption[] = OW2_DIVISIONS_DESC.flatMap((division) =>
  [1, 2, 3, 4, 5].map((tier) => ({
    label: `${division.charAt(0).toUpperCase()}${division.slice(1)} ${tier}`,
    value: defaultRankForCell(division, tier),
  }))
);

export function buildMappingCells(stored: RankMappingEntry[]): RankMappingEntry[] {
  const byKey = new Map(stored.map((e) => [`${e.division.toLowerCase()}-${e.tier}`, e]));
  const cells: RankMappingEntry[] = [];
  for (const division of OW2_DIVISIONS_DESC) {
    for (let tier = 1; tier <= 5; tier++) {
      const existing = byKey.get(`${division}-${tier}`);
      cells.push({
        division,
        tier,
        rank_value: existing?.rank_value ?? defaultRankForCell(division, tier)
      });
    }
  }
  return cells;
}
