import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import type { FilterDef } from "@/components/kit/useFilters";
import type { Stage } from "@/types/tournament.types";

/**
 * The chips that narrow the dispute list, all of them URL-backed so a narrowed
 * view can be pasted to whoever has to settle it.
 */
export function encounterReportFilterDefs({
  tournamentId,
  tournaments,
  stages
}: Readonly<{
  tournamentId: number | null;
  tournaments: Array<{ id: number; name: string }>;
  stages: Stage[];
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
  list.push(
    {
      key: "result_status",
      label: "Result",
      // The endpoint's field is a list and the service repeats the param once
      // per checked value, so this narrows to several states at once.
      kind: "multi",
      options: [
        { value: "none", label: "None" },
        { value: "pending_confirmation", label: "Pending confirmation" },
        { value: "confirmed", label: "Confirmed" },
        { value: "disputed", label: "Disputed" }
      ]
    },
    {
      key: "reported_count",
      label: "Reports filed",
      // `reported_count` is a scalar on the endpoint, so this is single
      // select: "0 or 2" is not a question the query param can ask.
      kind: "single",
      options: [
        { value: "0", label: "No reports" },
        { value: "1", label: "Awaiting second" },
        { value: "2", label: "Both reported" }
      ]
    },
    // Looks like `result_status: disputed` but is not: that is the recorded
    // result state, this is the live disagreement between two reports. A
    // dispute an admin already settled still has two divergent reports on
    // file, which is why they are two filters.
    { key: "mismatch_only", label: "Reports disagree", kind: "toggle" }
  );
  return list;
}
