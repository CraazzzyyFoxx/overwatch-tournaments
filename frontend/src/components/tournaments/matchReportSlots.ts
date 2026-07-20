import type { EncounterMapPoolState } from "@/types/tournament.types";

export interface MapCodeSlot {
  /** 1-based map number in the series; used as `map_index` in the payload. */
  mapIndex: number;
  /** Resolved map id when the slot maps to a picked pool entry, else null. */
  mapId: number | null;
}

const DEFAULT_BEST_OF = 3;

/**
 * Build the per-map replay-code slots for a captain report.
 *
 * When the map pool has PICKED entries, one named slot per pick ordered by the
 * pick `order` (map_index = that order, map_id soft-bound). Otherwise fall back
 * to `best_of` unnamed slots (map_index 1..best_of), defaulting to 3 when the
 * series length is unknown.
 */
export function buildMapCodeSlots(
  poolState: EncounterMapPoolState | null | undefined,
  bestOf: number | null | undefined
): MapCodeSlot[] {
  const picked = (poolState?.pool ?? [])
    .filter((entry) => entry.status === "picked")
    .slice()
    .sort((a, b) => a.order - b.order);

  if (picked.length > 0) {
    return picked.map((entry) => ({ mapIndex: entry.order, mapId: entry.map_id }));
  }

  const count = bestOf && bestOf > 0 ? bestOf : DEFAULT_BEST_OF;
  return Array.from({ length: count }, (_, index) => ({
    mapIndex: index + 1,
    mapId: null,
  }));
}
