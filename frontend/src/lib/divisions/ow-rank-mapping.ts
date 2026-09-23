import { OW_DIVISIONS_DESC, TIER_NUMBERS, owRankValue } from "@/lib/divisions/ow-ladder";
import type { RankMappingEntry } from "@/types/admin.types";

/**
 * Identity of the backend's built-in division+tier -> rank_value table
 * (`DEFAULT_RANK_MAPPING_VERSION` in `shared/schemas/settings.py`). Bumped
 * whenever that table is rebased — a bare `rank_value` is ambiguous across
 * versions (2500 was Platinum 5 under v1, Emerald 5 under v2).
 */
export const DEFAULT_RANK_MAPPING_VERSION = "ow2-default-v2";

/** The ladder's `rank_value` for a native division + tier; `0` if unknown. */
export function defaultRankForCell(division: string, tier: number): number {
  return owRankValue(division, tier) ?? 0;
}

export function buildMappingCells(stored: RankMappingEntry[]): RankMappingEntry[] {
  const byKey = new Map(stored.map((e) => [`${e.division.toLowerCase()}-${e.tier}`, e]));
  const cells: RankMappingEntry[] = [];
  for (const division of OW_DIVISIONS_DESC) {
    for (const tier of TIER_NUMBERS) {
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
