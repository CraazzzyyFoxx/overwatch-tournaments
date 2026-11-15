import type { FilterDef, FilterOption } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import type { Stage, StageItem } from "@/types/tournament.types";

/**
 * The chips an admin narrows the encounter list with.
 *
 * Everything narrowable lives in the URL, so `?stage=` survives a move to the
 * Standings or Reports view beside it — which is why this is a list of
 * definitions rather than a row of local selects.
 *
 * The tournament chip only exists where the tournament is not already pinned;
 * its options are `tournamentOptions` (the filtered game's, or every game's).
 * A stage or group filter with fewer than two options is not offered:
 * `FilterBar` drops it, while a value already in the URL stays removable.
 */
export function encounterFilterDefs({
  tournamentId,
  tournaments,
  stages,
  stageItems,
  t
}: Readonly<{
  tournamentId: number | null;
  tournaments: FilterOption[];
  stages: Stage[];
  stageItems: StageItem[];
  t: (key: string) => string;
}>): FilterDef[] {
  const list: FilterDef[] = [];
  if (tournamentId == null) {
    list.push({
      key: TOURNAMENT_QUERY_PARAM,
      label: t("tournament"),
      kind: "single",
      options: tournaments
    });
  }
  list.push(
    {
      key: "stage",
      label: t("stage"),
      kind: "single",
      options: stages.map((stage) => ({ value: String(stage.id), label: stage.name }))
    },
    {
      key: "group",
      label: t("group"),
      kind: "single",
      options: stageItems.map((item) => ({ value: String(item.id), label: item.name }))
    }
  );
  list.push(
    {
      key: "status",
      label: t("status"),
      kind: "single",
      options: [
        { value: "OPEN", label: t("open") },
        { value: "PENDING", label: t("pending") },
        { value: "COMPLETED", label: t("completed") }
      ]
    },
    {
      key: "has_logs",
      label: t("logs"),
      kind: "single",
      options: [
        { value: "true", label: t("logsAvailable") },
        { value: "false", label: t("noLogs") }
      ]
    }
  );
  return list;
}
