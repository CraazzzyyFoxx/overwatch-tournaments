import { TOURNAMENT_QUERY_PARAM } from "@/components/admin/tournament-filter";
import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { EncounterReportsStats } from "@/types/admin.types";
import type { Stage } from "@/types/tournament.types";

/**
 * The chips that narrow the dispute list, all of them URL-backed so a narrowed
 * view can be pasted to whoever has to settle it.
 */
export function encounterReportFilterDefs({
  tournamentId,
  tournaments,
  stages,
  stats,
  t
}: Readonly<{
  tournamentId: number | null;
  tournaments: Array<{ id: number; name: string }>;
  stages: Stage[];
  /** Scope-wide counters, shown as option counts; they ignore the chips themselves. */
  stats: EncounterReportsStats | undefined;
  t: (key: string) => string;
}>): FilterDef[] {
  const list: FilterDef[] = [];
  if (tournamentId == null) {
    list.push({
      key: TOURNAMENT_QUERY_PARAM,
      label: t("tournament"),
      kind: "single",
      options: tournaments.map((entry) => ({ value: String(entry.id), label: entry.name }))
    });
  }
  // A single stage is not a choice: `FilterBar` drops the filter, while a
  // value already in the URL stays removable.
  list.push({
    key: "stage",
    label: t("stage"),
    kind: "single",
    options: stages.map((stage) => ({ value: String(stage.id), label: stage.name }))
  });
  list.push(
    {
      key: "result_status",
      label: t("result"),
      // The endpoint's field is a list and the service repeats the param once
      // per checked value, so this narrows to several states at once.
      kind: "multi",
      options: [
        { value: "none", label: t("none") },
        { value: "pending_confirmation", label: t("pendingConfirmation") },
        { value: "confirmed", label: t("confirmed"), count: stats?.by_result_status.confirmed },
        { value: "disputed", label: t("disputed"), count: stats?.by_result_status.disputed }
      ]
    },
    {
      key: "reported_count",
      label: t("captainReports"),
      // `reported_count` is a scalar on the endpoint, so this is single
      // select: "0 or 2" is not a question the query param can ask.
      kind: "single",
      options: [
        { value: "0", label: t("noReports") },
        { value: "1", label: t("awaitingSecond"), count: stats?.awaiting_second_count },
        { value: "2", label: t("bothReported") }
      ]
    },
    // Looks like `result_status: disputed` but is not: that is the recorded
    // result state, this is the live disagreement between two reports. A
    // dispute an admin already settled still has two divergent reports on
    // file, which is why they are two filters.
    { key: "mismatch_only", label: t("reportsDisagree"), kind: "toggle" }
  );
  return list;
}
