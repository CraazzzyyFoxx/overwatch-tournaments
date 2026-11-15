import type { useTranslations } from "next-intl";

import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import type { Stage, StageItem } from "@/types/tournament.types";

/** The `adminTournaments.standings` translator of the browser that renders the chips. */
type StandingsTranslator = ReturnType<typeof useTranslations<"adminTournaments.standings">>;

/**
 * The chips that narrow the standings table.
 *
 * The tournament chip only exists where the tournament is not already pinned,
 * and the stage/group chips only once the scope has any: a chip with no options
 * is a control that cannot answer the question it asks.
 */
export function standingFilterDefs({
  tournamentId,
  stageId,
  tournaments,
  stages,
  stageItems,
  t
}: Readonly<{
  tournamentId: number | null;
  stageId?: number;
  tournaments: Array<{ id: number; name: string }>;
  stages: Stage[];
  stageItems: StageItem[];
  t: StandingsTranslator;
}>): FilterDef[] {
  const list: FilterDef[] = [];
  if (tournamentId == null) {
    list.push({
      key: TOURNAMENT_QUERY_PARAM,
      label: t("filters.tournament"),
      kind: "single",
      options: tournaments.map((entry) => ({
        value: String(entry.id),
        label: entry.name
      }))
    });
  }
  // Scoped to one stage there is nothing to pick: the stage is a pinned chip.
  if (stageId == null && stages.length > 0) {
    list.push({
      key: "stage",
      label: t("filters.stage"),
      kind: "single",
      options: stages.map((stage) => ({ value: String(stage.id), label: stage.name }))
    });
  }
  if (stageItems.length > 0) {
    list.push({
      key: "group",
      label: t("filters.group"),
      kind: "single",
      options: stageItems.map((item) => ({ value: String(item.id), label: item.name }))
    });
  }
  return list;
}
