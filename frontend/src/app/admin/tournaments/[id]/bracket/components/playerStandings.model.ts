import type { PlayerStanding, PlayerStandingPin } from "@/types/admin.types";

/** Unsaved pin edits by workspace member: a place, or `null` for "unpinned". */
export type PinEdits = Readonly<Record<number, number | null>>;

/** A row of the stage's personal table, with what the table draws off its role. */
export interface PlayerStandingRow extends PlayerStanding {
  /** Its draft pin when edited, else the saved one (a pinned row's `position` IS its pin). */
  pin: number | null;
  /** Players in its role: places are per role, so the highest place a pin can take. */
  roleSize: number;
  /** Its role's last qualifier with someone below: the playoff cut runs under this row. */
  atCut: boolean;
}

/**
 * The rows in the server's order (role by shape order, then place). The server
 * marks qualifiers per role, so each role has its own cut.
 */
export function standingRows(rows: readonly PlayerStanding[], edits: PinEdits): PlayerStandingRow[] {
  const roleSize = new Map<string, number>();
  const lastOfRole = new Map<string, number>();
  const lastQualified = new Map<string, number>();
  for (const row of rows) {
    roleSize.set(row.role, (roleSize.get(row.role) ?? 0) + 1);
    lastOfRole.set(row.role, row.workspace_member_id);
    if (row.is_qualified) lastQualified.set(row.role, row.workspace_member_id);
  }
  return rows.map((row) => {
    const edited = edits[row.workspace_member_id];
    return {
      ...row,
      pin: edited !== undefined ? edited : row.is_pinned ? row.position : null,
      roleSize: roleSize.get(row.role) ?? 0,
      atCut:
        lastQualified.get(row.role) === row.workspace_member_id &&
        lastOfRole.get(row.role) !== row.workspace_member_id
    };
  });
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
