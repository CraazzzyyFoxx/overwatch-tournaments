import type { PlayerStanding } from "@/types/tournament.types";

/**
 * The personal table in one list, by place. Places count inside a role, so a
 * place repeats once per role: equal places keep the API's role order (it
 * orders rows by stage, role in roster-shape order, then place). Unranked rows
 * (`position` null, before the standings job has run once) go last, by rank.
 */
export function orderPlayerStandings(rows: readonly PlayerStanding[]): PlayerStanding[] {
  return [...rows].sort((a, b) => {
    if (a.position == null || b.position == null) {
      return a.position == null ? (b.position == null ? b.rank - a.rank : 1) : -1;
    }
    return a.position - b.position;
  });
}

/**
 * The player the cut line goes under in rows of one role ordered by place: the
 * last qualified one. `null` when nobody qualifies, or when everybody does (a
 * line under the last row cuts nothing).
 */
export function playerStandingsCutAfter(rows: readonly PlayerStanding[]): number | null {
  const last = rows.findLastIndex((row) => row.is_qualified);
  return last >= 0 && last < rows.length - 1 ? rows[last].workspace_member_id : null;
}
