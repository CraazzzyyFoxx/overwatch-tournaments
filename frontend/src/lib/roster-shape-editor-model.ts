/**
 * The roster-shape editor's state machine, kept out of the component so it can
 * be tested without rendering: which mode a stored override maps to, what each
 * mode transition does to the slot counts, when the total is savable, what the
 * captain will actually see, and what goes on the wire.
 *
 * Domain rules still live on the server (`shared/domain/roster_shape.py`) and
 * reach the UI as a resolved `RosterShape`. The only two things duplicated here
 * are the savable-total bounds and the unsaved rounds preview, both of which
 * exist purely so the admin sees the verdict before a round trip -- see the
 * comments on each.
 */

import {
  ROSTER_PRESETS,
  ROSTER_SLOT_CODES,
  orderSlotCodes,
  presetForSlots,
  slotsTotal,
  type RosterPresetId,
  type RosterShape,
  type RosterSlotCode,
  type RosterSlotMap
} from "@/lib/roster-shape";

/**
 * `inherit` is a first-class mode, NOT "custom that happens to match the
 * default": it stores `null` and keeps following the workspace, so it must stay
 * distinguishable from an override with identical counts.
 */
export type RosterShapeMode = "inherit" | RosterPresetId | "custom";

export const ROSTER_SHAPE_MODES: readonly RosterShapeMode[] = [
  "inherit",
  ...ROSTER_PRESETS.map(({ id }) => id),
  "custom"
];

/**
 * Savable slot totals. The server owns this rule (`MIN_TEAM_SIZE` /
 * `MAX_TEAM_SIZE`); it is repeated here only to turn a guaranteed 422 into an
 * inline message, and the bounds are asserted against the server's own error
 * codes by the backend suite.
 */
export const MIN_ROSTER_TOTAL = 2;
export const MAX_ROSTER_TOTAL = 12;

/** Per-code stepper range. Zero means "no slot of this kind". */
export const MAX_SLOT_COUNT = MAX_ROSTER_TOTAL;

export interface RosterShapeSelection {
  mode: RosterShapeMode;
  /**
   * The counts the steppers show. Kept populated even in `inherit` mode so
   * switching to an override starts from the shape currently in force instead of
   * an empty form.
   */
  slots: RosterSlotMap;
}

export type RosterTotalError = "too_few" | "too_many";

/** Drop zeros and re-key in canonical order, matching what the server stores. */
export function normalizeSlots(slots: RosterSlotMap): RosterSlotMap {
  const normalized: RosterSlotMap = {};
  for (const code of orderSlotCodes(slots)) {
    normalized[code] = slots[code];
  }
  return normalized;
}

/** Which mode a stored override represents. `null` (no override) is `inherit`. */
export function modeForOverride(override: RosterSlotMap | null): RosterShapeMode {
  return override === null ? "inherit" : presetForSlots(override);
}

/**
 * Opening state: the stored override decides the mode, and the steppers are
 * seeded from the override when there is one, otherwise from the shape being
 * inherited.
 */
export function initialSelection(
  override: RosterSlotMap | null,
  inherited: RosterSlotMap
): RosterShapeSelection {
  return {
    mode: modeForOverride(override),
    slots: normalizeSlots(override ?? inherited)
  };
}

/**
 * Mode switch. A preset replaces the counts; `custom` keeps whatever is there;
 * `inherit` keeps them too, so toggling back and forth does not lose the numbers
 * the admin just typed.
 */
export function selectMode(
  selection: RosterShapeSelection,
  mode: RosterShapeMode
): RosterShapeSelection {
  const preset = ROSTER_PRESETS.find(({ id }) => id === mode);
  return {
    mode,
    slots: preset ? normalizeSlots(preset.slots) : selection.slots
  };
}

/**
 * Stepper edit. Counts are clamped, and the mode is re-derived from the result:
 * hand-typing 1/2/2 snaps the select back to `Overwatch 5v5` rather than leaving
 * it lying that the shape is bespoke.
 */
export function setSlotCount(
  selection: RosterShapeSelection,
  code: RosterSlotCode,
  count: number
): RosterShapeSelection {
  const clamped = Math.min(Math.max(Math.round(count), 0), MAX_SLOT_COUNT);
  const slots = normalizeSlots({ ...selection.slots, [code]: clamped });
  return { mode: presetForSlots(slots), slots };
}

/**
 * Why the payload cannot be saved, if it cannot. Takes the payload rather than
 * the selection so the editor and the settings tab -- which holds only the
 * payload -- gate on the exact same check instead of two lookalikes.
 */
export function payloadTotalError(payload: RosterSlotMap | null): RosterTotalError | null {
  // Inherit sends no counts, so nothing can be out of range.
  if (payload === null) return null;
  const total = slotsTotal(payload);
  if (total < MIN_ROSTER_TOTAL) return "too_few";
  if (total > MAX_ROSTER_TOTAL) return "too_many";
  return null;
}

/**
 * Draft rounds for the total on screen. When the total matches the shape the
 * server already resolved, this IS the server's `draft_rounds` -- no rule is
 * reimplemented. Only a total the server has never seen falls back to the
 * arithmetic, because the editor cannot ask mid-keystroke; the value the admin
 * keeps is always the server's.
 */
export function draftRoundsPreview(total: number, effective: RosterShape): number {
  return total === effective.team_size ? effective.draft_rounds : total - 1;
}

/**
 * The slot list a captain sees: one row per slot, so `{tank: 1, flex: 5}` reads
 * as one Tank and five Flex instead of a pair of counters the admin has to
 * expand in their head.
 */
export function previewSlotRows(slots: RosterSlotMap): RosterSlotCode[] {
  return ROSTER_SLOT_CODES.flatMap((code) =>
    Array.from({ length: slots[code] ?? 0 }, () => code)
  );
}

/**
 * What goes into `TournamentUpdate.roster_slots_json`: `null` in `inherit` mode,
 * a normalized map otherwise. Normalizing here keeps the JSON key order stable,
 * which is what the tab's dirty check compares.
 */
export function slotsPayload(selection: RosterShapeSelection): RosterSlotMap | null {
  return selection.mode === "inherit" ? null : normalizeSlots(selection.slots);
}
