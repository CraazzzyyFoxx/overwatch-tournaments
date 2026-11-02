import type { PlayerStanding } from "@/types/tournament.types";

/** One role's table of one individual Swiss stage. */
export type PlayerStandingsGroup = {
  key: string;
  stageId: number;
  role: string;
  rows: PlayerStanding[];
  /**
   * Index of the last qualified row: the cut line is drawn under it. `null`
   * when nobody qualifies yet, or when everybody does (a line under the last
   * row cuts nothing).
   */
  cutAfter: number | null;
};

/**
 * Splits the personal table into one group per stage and role. The API already
 * orders rows by stage, role (roster-shape order) and place, so groups keep
 * their first-appearance order; each group's rows are re-sorted by place only
 * to survive an unranked table (`position` null sorts last, ties by rank).
 */
export function groupPlayerStandings(rows: readonly PlayerStanding[]): PlayerStandingsGroup[] {
  const groups = new Map<string, PlayerStandingsGroup>();
  for (const row of rows) {
    const key = `${row.stage_id}:${row.role}`;
    const group = groups.get(key) ?? {
      key,
      stageId: row.stage_id,
      role: row.role,
      rows: [],
      cutAfter: null
    };
    group.rows.push(row);
    groups.set(key, group);
  }
  return [...groups.values()].map((group) => {
    const sorted = [...group.rows].sort(
      (a, b) =>
        (a.position ?? Number.POSITIVE_INFINITY) - (b.position ?? Number.POSITIVE_INFINITY) ||
        b.rank - a.rank
    );
    const last = sorted.findLastIndex((row) => row.is_qualified);
    return { ...group, rows: sorted, cutAfter: last >= 0 && last < sorted.length - 1 ? last : null };
  });
}
