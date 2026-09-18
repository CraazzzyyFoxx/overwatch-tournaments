/**
 * The roster slot vocabulary the server speaks, plus the little UI sugar the
 * admin roster form needs.
 *
 * There is deliberately NO domain rule here. What a valid roster shape is, what
 * it falls back to, how many draft rounds it implies -- all of that lives once,
 * in `backend/shared/domain/roster_shape.py`, and reaches the frontend as a
 * resolved `RosterShape`. Recomputing any of it here would recreate exactly the
 * mirror this feature exists to delete.
 */

import type { PlayerRoleSlotCode } from "@/lib/player-role";

export type RosterSlotCode = PlayerRoleSlotCode;

/**
 * Canonical order, matching `shared.domain.roster_shape.ROSTER_SLOT_CODES`.
 * The server normalizes stored slot maps into this order; the frontend uses it
 * to render counters in a stable sequence regardless of JSON key order.
 */
export const ROSTER_SLOT_CODES: readonly RosterSlotCode[] = ["tank", "damage", "support", "flex"];

/**
 * A slot map. The server rejects any key outside `ROSTER_SLOT_CODES` and never
 * stores a zero count, so a map that came off the wire has only present codes
 * with counts >= 1. An in-progress editor map may hold zeros.
 */
export type RosterSlotMap = Partial<Record<RosterSlotCode, number>>;

/**
 * A resolved roster shape exactly as `shared.schemas.roster_slots.RosterShapeRead`
 * serializes it. Every derived value is a server field: read `team_size`,
 * `draft_rounds` and `has_role_slots` from here, never recompute them.
 */
export interface RosterShape {
  /** Normalized: no zero counts, canonical order. */
  slots: RosterSlotMap;
  team_size: number;
  flex_slots: number;
  /** `false` only when every slot is flex, i.e. no slot asks for a role. */
  has_role_slots: boolean;
  draft_rounds: number;
  /**
   * Which level the shape came from. `host`/`user` are the pickup-mix levels:
   * the account hosting the mix pins one (`user` when the account itself is
   * being read, `host` when a mix is). `null` from readers that resolve only
   * the effective shape, not its level.
   */
  source: "tournament" | "host" | "user" | "workspace" | "default" | null;
}

export type RosterPresetId = "ow5v5" | "flex6";

/** The two shapes worth one click in the admin form; anything else is custom. */
export const ROSTER_PRESETS: readonly { readonly id: RosterPresetId; readonly slots: RosterSlotMap }[] = [
  { id: "ow5v5", slots: { tank: 1, damage: 2, support: 2 } },
  { id: "flex6", slots: { flex: 6 } }
];

/** Present codes in canonical order. Absent (and zeroed) codes are dropped. */
export function orderSlotCodes(slots: RosterSlotMap): RosterSlotCode[] {
  return ROSTER_SLOT_CODES.filter((code) => (slots[code] ?? 0) > 0);
}

/** A slot code that names a role, i.e. anything but `flex`. */
export type RosterRoleSlotCode = Exclude<RosterSlotCode, "flex">;

/**
 * Every slot code except `flex` asks for a specific role. A type guard so
 * callers can hand the narrowed code straight to role-keyed lookups.
 */
export function isRoleSlotCode(code: string): code is RosterRoleSlotCode {
  return code !== "flex";
}

/**
 * Whether a wire string is a slot code we know. A type guard so callers can hand
 * the narrowed code to the slot-keyed translations, which are typed to the union
 * — an unknown code from a newer server must render as itself, not as a key.
 */
export function isRosterSlotCode(code: string): code is RosterSlotCode {
  return (ROSTER_SLOT_CODES as readonly string[]).includes(code);
}

/**
 * Live total of a slot map still being edited. This is NOT a stand-in for
 * `RosterShape.team_size`: wherever a server shape exists, read `team_size` off
 * it. This exists only for the roster-shape editor, where the steppers move
 * faster than any round trip and no server shape exists yet.
 */
export function slotsTotal(slots: RosterSlotMap): number {
  return ROSTER_SLOT_CODES.reduce((total, code) => total + (slots[code] ?? 0), 0);
}

/** Which preset a slot map equals, ignoring key order. */
export function presetForSlots(slots: RosterSlotMap): RosterPresetId | "custom" {
  const codes = orderSlotCodes(slots);
  const preset = ROSTER_PRESETS.find(({ slots: presetSlots }) => {
    const presetCodes = orderSlotCodes(presetSlots);
    return (
      presetCodes.length === codes.length &&
      presetCodes.every((code, index) => code === codes[index] && presetSlots[code] === slots[code])
    );
  });
  return preset?.id ?? "custom";
}
