import type { PickBanEntry, PickBanState } from "@/types/tournament.types";

export interface MapCodeSlot {
  /** 1-based map number in the series; used as `map_index` in the payload. */
  mapIndex: number;
  /** Resolved map id when the slot maps to a settled pool entry, else null. */
  mapId: number | null;
}

const DEFAULT_BEST_OF = 3;

/** Play order: the veto's global action order, falling back to the pool order. */
function playOrder(entry: PickBanEntry): number {
  return entry.action_index ?? entry.order;
}

/**
 * Build the per-map replay-code slots for a captain report.
 *
 * When the veto has settled maps, one named slot per map in PLAY order, indexed
 * from 1. `entry.order` is deliberately not the index: it is a per-round
 * display/tiebreak field that starts at 0 and is spaced by `round * 1000`
 * (backend `pick_ban_session.advance_to_next_round`), so using it sent
 * `map_index: 0` — which the server rejects — and `1000` for a second map.
 *
 * A picked map counts as settled whether or not its game is confirmed: the
 * series report is filed once every map has been played, at which point the
 * captain needs a slot per map the room just named.
 *
 * With no settled maps at all, fall back to `best_of` unnamed slots
 * (map_index 1..best_of), defaulting to 3 when the series length is unknown.
 * Mirrored server-side by `report_form.series_map_indices`.
 */
export function buildMapCodeSlots(
  poolState: PickBanState | null | undefined,
  bestOf: number | null | undefined
): MapCodeSlot[] {
  const settled = (poolState?.pool ?? [])
    .filter((entry) => entry.status === "picked")
    .slice()
    .sort((a, b) => playOrder(a) - playOrder(b));

  if (settled.length > 0) {
    return settled.map((entry, index) => ({ mapIndex: index + 1, mapId: entry.item_id }));
  }

  const count = bestOf && bestOf > 0 ? bestOf : DEFAULT_BEST_OF;
  return Array.from({ length: count }, (_, index) => ({
    mapIndex: index + 1,
    mapId: null,
  }));
}
