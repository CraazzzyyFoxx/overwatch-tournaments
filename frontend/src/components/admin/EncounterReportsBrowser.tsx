"use client";

import { useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ClipboardCheck, Clock3, Gavel, ScrollText } from "lucide-react";

import { AdminDataTable } from "@/components/data-table";
import { ResolveResultDialog } from "@/components/admin/ResolveResultDialog";
import { StatTile, StatTileGrid } from "@/components/admin/StatTile";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { useFilters } from "@/components/kit/useFilters";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam
} from "@/components/admin/tournament-filter";
import { Button } from "@/components/ui/button";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import type { EncounterReportsRow } from "@/types/admin.types";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

import { encounterReportFilterDefs } from "./encounter-reports/filters";
import { ReportInspectorPanel } from "./encounter-reports/ReportInspectorPanel";
import { useEncounterReportColumns } from "./encounter-reports/useEncounterReportColumns";
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
  canUpdateEncounter,
  tournamentName
}: Readonly<{
  /** `null` = every tournament in the workspace. */
  tournamentId: number | null;
  workspaceId: number | null;
  canUpdateEncounter: boolean;
  /** Names the pinned chip inside a hub; the chip reads `#id` without it. */
  tournamentName?: string | null;
}>) {
  const queryClient = useQueryClient();
  // `id` is the inspector, not a filter: opening a row must not drop its page.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
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
        stages: scope.stages
      }),
    [tournamentId, scope.tournaments, scope.stages]
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
    return (
      <EmptyNote>
        Captain reports are scoped to a workspace. Pick one to see what has been reported.
      </EmptyNote>
    );
  }

  return (
    <div className="space-y-3">
      <StatTileGrid>
        <StatTile
          label="Confirmed"
          value={stats?.by_result_status.confirmed ?? 0}
          icon={ClipboardCheck}
          tone="success"
        />
        <StatTile
          label="Disputed"
          value={stats?.by_result_status.disputed ?? 0}
          detail="Recorded result state"
          icon={AlertTriangle}
          tone="danger"
        />
        <StatTile
          label="Reports disagree"
          value={stats?.mismatch_count ?? 0}
          detail="Both captains reported, scores differ"
          icon={ScrollText}
          tone="warning"
        />
        <StatTile
          label="Awaiting second"
          value={stats?.awaiting_second_count ?? 0}
          detail="One captain has reported"
          icon={Clock3}
          tone="info"
        />
      </StatTileGrid>

      <p className="text-sm text-muted-foreground">
        Both captains report independently. Matching scores confirm the encounter; a disagreement
        marks it disputed.
      </p>

      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <AdminDataTable<EncounterReportsRow>
            columns={columns}
            filterKey={filters.filterKey}
            initialPageSize={PAGE_SIZE}
            columnsStorageKey="encounter-reports-table-columns"
            searchPlaceholder="Search team or encounter"
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            toolbar={
              <FilterBar
                defs={defs}
                filters={filters}
                pinned={
                  tournamentId != null
                    ? [
                        {
                          key: TOURNAMENT_QUERY_PARAM,
                          label: `Tournament: ${tournamentName ?? `#${tournamentId}`}`
                        }
                      ]
                    : undefined
                }
              />
            }
            emptyMessage="No encounters match this filter."
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{row.original.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {row.original.home_team?.name ?? "?"} vs {row.original.away_team?.name ?? "?"} ·{" "}
                  {row.original.reported_count}/2 reported
                </p>
                <p className="text-xs text-muted-foreground">{row.original.result_status}</p>
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
            queryFn={async (page, search, pageSize) => {
              const result = await adminService.listEncounterReports({
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
              });
              // The inspector pages through the rows on screen, and the table
              // owns the fetch, so this is where that page is observed.
              setPageRows(result.results);
              return result;
            }}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow ? openRow.name : ""}
          subtitle={
            openRow
              ? `${showTournament ? `${openRow.tournament_name ?? "Unknown tournament"} · ` : ""}${openRow.stage_name ?? "Unassigned"} · Round ${openRow.round} · BO${openRow.best_of}`
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
              <Button type="button" size="sm" variant="secondary" onClick={() => setResolving(openRow)}>
                <Gavel aria-hidden className="size-3.5" />
                {openRow.result_status === "confirmed" ? "Review result" : "Resolve result"}
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
