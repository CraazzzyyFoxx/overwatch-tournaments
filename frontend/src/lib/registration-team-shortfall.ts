import { ROSTER_SLOT_CODES, type RosterSlotCode } from "@/lib/roster-shape";

/** A next-intl translator scoped to `rosterShape.slotCodes`. */
export type SlotLabelTranslator = (code: RosterSlotCode) => string;

/**
 * "What this roster still needs", rendered from the structured `open_slots` map.
 *
 * The API also ships a ready-made `shortfall` string, built by the backend's
 * `RosterOccupancy.describe_shortfall()`, which reads `"1x damage, 2x support"` — raw
 * slot codes in an English shape, and it was being interpolated verbatim into a
 * Russian sentence. Building it here fixes that.
 *
 * The labels come from `rosterShape.slotCodes`, the SAME translated set the slot
 * chips elsewhere in these cards use. An earlier version of this reached for
 * `ROLE_LABELS` (hardcoded English, and with no `flex` entry), which made one card
 * read "1× DPS" in its shortfall and "Damage" on its invite chip, and rendered a
 * flex slot as the raw code.
 *
 * The server's field stays the source of TRUTH — it is computed against the
 * tournament's real roster shape. This owns only the presentation of the same
 * numbers, which is where presentation belongs.
 */
export function formatShortfall(
  openSlots: Partial<Record<RosterSlotCode, number>>,
  slotLabel: SlotLabelTranslator,
): string {
  return ROSTER_SLOT_CODES.filter((code) => (openSlots[code] ?? 0) > 0)
    .map((code) => `${openSlots[code]}× ${slotLabel(code)}`)
    .join(", ");
}
