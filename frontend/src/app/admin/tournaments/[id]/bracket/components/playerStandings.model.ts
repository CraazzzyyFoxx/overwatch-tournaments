import type { PlayerStanding, PlayerStandingPin } from "@/types/admin.types";

/** One role's personal table, in the server's order (role by shape order, then place). */
export interface RoleTable {
  role: string;
  rows: PlayerStanding[];
}

/** Unsaved pin edits by workspace member: a place, or `null` for "unpinned". */
export type PinEdits = Readonly<Record<number, number | null>>;

export function tablesByRole(rows: readonly PlayerStanding[], stageId: number): RoleTable[] {
  const tables = new Map<string, PlayerStanding[]>();
  for (const row of rows) {
    if (row.stage_id !== stageId) continue;
    tables.set(row.role, [...(tables.get(row.role) ?? []), row]);
  }
  return [...tables].map(([role, tableRows]) => ({ role, rows: tableRows }));
}

/** A pinned row's `position` IS its pin (the server places a pin before anything else). */
function savedPins(rows: readonly PlayerStanding[]): Map<number, number> {
  return new Map(
    rows.flatMap((row) =>
      row.is_pinned && row.position != null ? [[row.workspace_member_id, row.position] as const] : []
    )
  );
}

function effectivePins(rows: readonly PlayerStanding[], edits: PinEdits): Map<number, number> {
  const pins = savedPins(rows);
  for (const [member, position] of Object.entries(edits)) {
    if (position == null) pins.delete(Number(member));
    else pins.set(Number(member), position);
  }
  return pins;
}

/** The pin a row shows: its draft when edited, else the saved one. */
export function pinOf(row: PlayerStanding, edits: PinEdits): number | null {
  const edited = edits[row.workspace_member_id];
  if (edited !== undefined) return edited;
  return row.is_pinned ? row.position : null;
}

export function pinsDirty(rows: readonly PlayerStanding[], edits: PinEdits): boolean {
  const saved = savedPins(rows);
  const next = effectivePins(rows, edits);
  return saved.size !== next.size || [...next].some(([member, position]) => saved.get(member) !== position);
}

/** The whole set of pins the PUT replaces the stage's pins with. */
export function pinsPayload(rows: readonly PlayerStanding[], edits: PinEdits): PlayerStandingPin[] {
  return [...effectivePins(rows, edits)].map(([workspace_member_id, position]) => ({
    workspace_member_id,
    position
  }));
}

/**
 * Index of the last qualified row of a role table: the playoff cut. `-1` when
 * nobody qualifies. The server marks qualifiers per role, so each table has its own.
 */
export function cutIndex(rows: readonly PlayerStanding[]): number {
  return rows.reduce((last, row, index) => (row.is_qualified ? index : last), -1);
}
