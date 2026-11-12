"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQueryClient } from "@tanstack/react-query";

import { DataTable } from "@craazzzyyfoxx/admin-kit/data-table";
import { ResolveResultDialog } from "@/components/admin/ResolveResultDialog";
import { FilterBar } from "@craazzzyyfoxx/admin-kit/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { useFilters } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam
} from "@/components/admin/tournament-filter";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { EncounterReportsRow } from "@/types/admin.types";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

import { ResultStatusPill } from "./encounters/EncounterCells";
import { encounterReportFilterDefs } from "./encounter-reports/filters";
import { ReportInspectorPanel } from "./encounter-reports/ReportInspectorPanel";
import { useEncounterReportColumns } from "./encounter-reports/useEncounterReportColumns";
import { seatsBySlot } from "@/lib/encounter/seats";
import { useEncounterReportScope } from "./encounter-reports/useEncounterReportScope";

const PAGE_SIZE = 25;

/**
 * Captain reports, for one tournament or for the whole workspace.
 *
 * One component rather than a hub tab and a near-identical browser page: the
 * two differ only by whether `tournamentId` is pinned, and a second copy of a
 * table with this much derived state would drift within a release.
 *
 * A dispute used to be invisible outside the per-encounter dialog; this lists
 * what needs attention and hands each row to the one write surface that can
 * settle it.
 *
 * Filters are chips in `FilterBar` and the row detail is `Inspector`,
 * so a narrowed list and the open row both travel in the URL — a disputed
 * encounter can be pasted to whoever has to settle it.
 */
export function EncounterReportsBrowser({
  tournamentId,
  workspaceId,
  canUpdateEncounter
}: Readonly<{
  /** `null` = every tournament in the workspace. */
  tournamentId: number | null;
  workspaceId: number | null;
  canUpdateEncounter: boolean;
}>) {
  const t = useTranslations("adminMatches.reports");
  const queryClient = useQueryClient();
  // `id` is the inspector, not a filter: opening a row must not drop its page.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;
  const [pageRows, setPageRows] = useState<EncounterReportsRow[]>([]);
  const [resolving, setResolving] = useState<EncounterReportsRow | null>(null);
  const showTournament = tournamentId == null;

  const chipTournamentId = parseTournamentQueryParam(
    searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null
  );
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const scope = useEncounterReportScope({ tournamentId, workspaceId, scopeTournamentId });
  const { customFields, stats } = scope;

  const defs = useMemo(
    () =>
      encounterReportFilterDefs({
        tournamentId,
        tournaments: scope.tournaments,
        stages: scope.stages,
        stats,
        t: t as unknown as (key: string) => string
      }),
    [tournamentId, scope.tournaments, scope.stages, stats, t]
  );

  const filters = useFilters(defs);
  const stageFilter = String(filters.values.stage ?? "");
  const resultStatusFilter = Array.isArray(filters.values.result_status)
    ? (filters.values.result_status as string[])
    : [];
  const reportedCountFilter = String(filters.values.reported_count ?? "");
  const mismatchOnly = filters.values.mismatch_only === true;

  // The inspector shows a row from the page on screen, so a deep-linked `?id=`
  // the current chips exclude leaves it closed rather than showing detail for
  // an encounter the list does not contain.
  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const columns = useEncounterReportColumns({ showTournament, customFields });

  if (workspaceId == null) {
    return <PageStateCard state="empty" description={t("scopePrompt")} />;
  }

  return (
    <div className="space-y-3">
      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <DataTable<EncounterReportsRow>
            columns={columns}
            filterKey={filters.filterKey}
            initialPageSize={PAGE_SIZE}
            columnsStorageKey="encounter-reports-table-columns"
            searchPlaceholder={t("search")}
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            toolbar={
              <FilterBar
                defs={defs}
                filters={filters}
              />
            }
            emptyMessage={t("empty")}
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{row.original.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {t("teamsReported", {
                    teams: seatsBySlot(row.original.participations)
                      .map((seat) => seat.name)
                      .join(` ${t("vs")} `),
                    count: row.original.reported_count,
                    total: row.original.participations.length
                  })}
                </p>
                <ResultStatusPill status={row.original.result_status} />
              </div>
            )}
            queryKey={(page, search, pageSize) => [
              "encounter-reports",
              {
                workspaceId,
                tournamentId: scopeTournamentId,
                mismatchOnly,
                page,
                search,
                pageSize,
                filters: {
                  stage: stageFilter,
                  result_status: resultStatusFilter,
                  reported_count: reportedCountFilter
                }
              }
            ]}
            queryFn={(page, search, pageSize) =>
              adminService.listEncounterReports({
                workspace_id: workspaceId,
                tournament_id: scopeTournamentId ?? undefined,
                stage_id: stageFilter ? Number(stageFilter) : undefined,
                query: search || undefined,
                result_status: resultStatusFilter.length ? resultStatusFilter : undefined,
                // Zero is a real value here ("neither captain reported"), so the
                // guard is on the string, never on the number.
                reported_count: reportedCountFilter ? Number(reportedCountFilter) : undefined,
                mismatch_only: mismatchOnly || undefined,
                page,
                per_page: pageSize
              })
            }
            onPageRowsChange={setPageRows}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow ? openRow.name : ""}
          subtitle={
            openRow
              ? t(showTournament ? "detailSubtitleWithTournament" : "detailSubtitle", {
                  tournament: openRow.tournament_name ?? t("unknownTournament"),
                  stage: openRow.stage_name ?? t("unassigned"),
                  round: openRow.round ?? "?",
                  bestOf: openRow.best_of
                })
              : undefined
          }
          onPrev={
            openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
          }
          onNext={
            openIndex >= 0 && openIndex < pageRows.length - 1
              ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
              : undefined
          }
          openHref={openRow ? `/encounters/${openRow.id}` : undefined}
          actions={
            openRow && canUpdateEncounter ? (
              <Button type="button" size="sm" variant="outline" onClick={() => setResolving(openRow)}>
                {openRow.result_status === "confirmed" ? t("review") : t("resolve")}
              </Button>
            ) : null
          }
        >
          {openRow ? <ReportInspectorPanel row={openRow} customFields={customFields} /> : null}
        </Inspector>
      </div>

      <ResolveResultDialog
        row={resolving}
        open={resolving != null}
        onOpenChange={(next) => setResolving(next ? resolving : null)}
        onResolved={() => {
          // A settled result moves the encounter, the standings and the
          // bracket, so the invalidation is wider than this list. Scoped to
          // prefixes rather than exact keys because the list key carries the
          // whole filter object and every variant of it is now stale.
          void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.reportsAll() });
          void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.all() });
          void queryClient.invalidateQueries({ queryKey: adminQueryKeys.matches() });
          void queryClient.invalidateQueries({
            queryKey: scopeTournamentId == null ? ["standings"] : ["standings", scopeTournamentId]
          });
          if (scopeTournamentId != null) {
            invalidateTournamentWorkspace(queryClient, scopeTournamentId, workspaceId);
          }
        }}
      />
    </div>
  );
}
