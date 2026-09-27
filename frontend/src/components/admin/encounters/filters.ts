import type { FilterDef } from "@/components/kit/useFilters";
import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import type { Stage, StageItem } from "@/types/tournament.types";

/**
 * The chips an admin narrows the encounter list with.
 *
 * Everything narrowable lives in the URL, so `?stage=` survives a move to the
 * Standings or Reports view beside it — which is why this is a list of
 * definitions rather than a row of local selects.
 *
 * The tournament chip only exists where the tournament is not already pinned,
 * and the stage/group chips only once the scope has any: a chip with no options
 * is a control that cannot answer the question it asks.
 */
export function encounterFilterDefs({
  tournamentId,
  tournaments,
  stages,
  stageItems
}: Readonly<{
  tournamentId: number | null;
  tournaments: Array<{ id: number; name: string }>;
  stages: Stage[];
  stageItems: StageItem[];
}>): FilterDef[] {
  const list: FilterDef[] = [];
  if (tournamentId == null) {
    list.push({
      key: TOURNAMENT_QUERY_PARAM,
      label: "Tournament",
      kind: "single",
      options: tournaments.map((entry) => ({ value: String(entry.id), label: entry.name }))
    });
  }
  if (stages.length > 0) {
    list.push({
      key: "stage",
      label: "Stage",
      kind: "single",
      options: stages.map((stage) => ({ value: String(stage.id), label: stage.name }))
    });
  }
  if (stageItems.length > 0) {
    list.push({
      key: "group",
      label: "Group",
      kind: "single",
      options: stageItems.map((item) => ({ value: String(item.id), label: item.name }))
    });
  }
  list.push(
    {
      key: "status",
      label: "Status",
      kind: "single",
      options: [
        { value: "OPEN", label: "Open" },
        { value: "PENDING", label: "Pending" },
        { value: "COMPLETED", label: "Completed" }
      ]
    },
    {
      key: "has_logs",
      label: "Logs",
      kind: "single",
      options: [
        { value: "true", label: "Logs available" },
        { value: "false", label: "No logs" }
      ]
    }
  );
  return list;
}
