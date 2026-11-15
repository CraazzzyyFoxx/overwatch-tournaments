import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { Tournament } from "@/types/tournament.types";

type FilterLabelKey = "filters.tournament" | "filters.hasAccount" | "filters.noIdentities";

/**
 * The chips on the people list. Each one is a server param on GET /admin/users
 * — the table is server-paged, so narrowing is the server's job.
 */
export function peopleFilterDefs(
  tournaments: readonly Tournament[],
  t: (key: FilterLabelKey) => string
): FilterDef[] {
  return [
    {
      key: TOURNAMENT_QUERY_PARAM,
      label: t("filters.tournament"),
      kind: "single",
      options: tournaments.map((tournament) => ({
        value: String(tournament.id),
        label: tournament.name
      }))
    },
    { key: "has-account", label: t("filters.hasAccount"), kind: "toggle" },
    { key: "unlinked", label: t("filters.noIdentities"), kind: "toggle" }
  ];
}
