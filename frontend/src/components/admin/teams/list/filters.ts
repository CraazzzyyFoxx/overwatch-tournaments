import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import type { FilterDef, FilterOption } from "@craazzzyyfoxx/admin-kit/kit/useFilters";

/** The chip that narrows the roster list by the tournament a team plays in (`tournamentOptions`). */
export function teamFilterDefs(tournaments: FilterOption[], tournamentLabel: string): FilterDef[] {
  return [
    {
      // The URL keeps the `tournament` spelling the sibling admin browsers
      // already use, so a link that pins a tournament still opens pinned.
      key: TOURNAMENT_QUERY_PARAM,
      label: tournamentLabel,
      kind: "single",
      options: tournaments
    }
  ];
}
