"use client";

import { useMemo, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw } from "lucide-react";

import { AdminDataTable } from "@/components/data-table";
import { EncounterForm } from "@/components/admin/EncounterForm";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import { hasChallongeSource } from "@/components/admin/tournament-checklist";
import { TOURNAMENT_QUERY_PARAM, parseTournamentQueryParam } from "@/components/admin/tournament-filter";
import { Button } from "@/components/ui/button";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { bracketRoundLabelEn, UNKNOWN_ROUND_SHAPE } from "@/lib/bracket/round-name";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import encounterService from "@/services/encounter.service";
import type { Encounter } from "@/types/encounter.types";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

import { encounterScopeLabel } from "./encounters/EncounterCells";
import { encounterFilterDefs } from "./encounters/filters";
import {
  EncounterInspectorActions,
  EncounterInspectorPanel
} from "./encounters/EncounterInspectorPanel";
import { useEncounterColumns } from "./encounters/useEncounterColumns";
import { useEncounterForm } from "./encounters/useEncounterForm";
import { useEncounterScope } from "./encounters/useEncounterScope";

const PAGE_SIZE = 15;

/**
 * Encounters, for one tournament or for the whole workspace.
 *
 * One component rather than a hub tab and a near-identical browser page: the
 * two differed only by whether the tournament is pinned, and the two copies had
 * already drifted — the hub's table offered no paging, no closeness and sent a
 * lowercase `status` the backend does not accept, while the browser page had no
 * stage scope at all.
 *
 * Everything the admin narrows by lives in the URL through `FilterBar`, so
 * `?stage=` survives a move to the Standings or Reports view beside it.
 */
export function EncountersBrowser({
  tournamentId,
  workspaceId
}: Readonly<{
  /** `null` = every tournament in the workspace, with the chip unpinned. */
  tournamentId: number | null;
  workspaceId: number | null;
}>) {
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row is on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const canCreate = canAccessPermission("match.create", workspaceId);
  const canUpdate = canAccessPermission("match.update", workspaceId);
  const canDelete = canAccessPermission("match.delete", workspaceId);
  // Encounter sync hits the Challonge import endpoint, so it is gated on the
  // Challonge grant rather than on `match.*`.
  const canSync = canAccessPermission("challonge.update", workspaceId);

  const [pageRows, setPageRows] = useState<Encounter[]>([]);
  const [pendingDelete, setPendingDelete] = useState<Encounter | null>(null);

  // Scope: pinned by the hub, or picked with a chip on the workspace browser.
  const chipTournamentId = parseTournamentQueryParam(
    searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null
  );
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const scope = useEncounterScope({ tournamentId, scopeTournamentId });
  const { stages, teams } = scope;

  const defs = useMemo(
    () =>
      encounterFilterDefs({
        tournamentId,
        tournaments: scope.tournaments,
        stages,
        stageItems: scope.stageItems
      }),
    [tournamentId, scope.tournaments, stages, scope.stageItems]
  );

  const filters = useFilters(defs);
  const stageFilter = String(filters.values.stage ?? "");
  const groupFilter = String(filters.values.group ?? "");
  const statusFilter = String(filters.values.status ?? "");
  const logsFilter = String(filters.values.has_logs ?? "");

  // The inspector shows a row from the page on screen, so a deep-linked `?id=`
  // that the current filters exclude leaves it closed rather than fetching an
  // encounter the list does not contain.
  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: encounterQueryKeys.all() });
    if (scopeTournamentId != null) {
      invalidateTournamentWorkspace(queryClient, scopeTournamentId, workspaceId);
    }
  };

  const form = useEncounterForm({ scopeTournamentId, stages, onSaved: invalidate });

  const deleteMutation = useMutation({
    mutationFn: (encounterId: number) => adminService.deleteEncounter(encounterId),
    onSuccess: () => {
      const removed = pendingDelete;
      invalidate();
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success("Encounter deleted");
    }
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncEncountersFromChallonge(scopeTournamentId!),
    onSuccess: () => {
      invalidate();
      notify.success("Encounters synced from Challonge");
    }
  });

  const columns = useEncounterColumns({
    canUpdate,
    canDelete,
    onEdit: form.openEdit,
    onDelete: setPendingDelete
  });

  if (workspaceId == null) {
    return (
      <EmptyNote>
        Encounters are scoped to a workspace. Pick one to see what has been scheduled.
      </EmptyNote>
    );
  }

  const challongeReady = hasChallongeSource(scope.tournament, stages);
  const reportsHref =
    tournamentId != null
      ? `/admin/tournaments/${tournamentId}/matches/reports`
      : "/admin/matches?view=reports";

  const trailing = (
    <>
      {canSync ? (
        <Button
          variant="outline"
          size="sm"
          disabled={syncMutation.isPending || scopeTournamentId == null || !challongeReady}
          onClick={() => syncMutation.mutate()}
        >
          <RefreshCw aria-hidden className="size-4" />
          Sync from Challonge
        </Button>
      ) : null}
      {canCreate ? (
        <Button
          size="sm"
          disabled={scopeTournamentId == null || stages.length === 0 || teams.length < 2}
          onClick={form.openCreate}
        >
          <Plus aria-hidden className="size-4" />
          Create encounter
        </Button>
      ) : null}
    </>
  );

  return (
    <div
      className={cn(
        "grid items-start gap-4",
        openRow && "lg:grid-cols-[minmax(0,1fr)_380px]"
      )}
    >
      <div className="min-w-0">
        <AdminDataTable<Encounter>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          searchPlaceholder="Search encounters…"
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={
            <FilterBar
              defs={defs}
              filters={filters}
              trailing={trailing}
              pinned={
                tournamentId != null
                  ? [
                      {
                        key: TOURNAMENT_QUERY_PARAM,
                        label: `Tournament: ${scope.tournament?.name ?? `#${tournamentId}`}`
                      }
                    ]
                  : undefined
              }
            />
          }
          emptyMessage={
            scopeTournamentId == null
              ? "No encounters yet. Pick a tournament to see its bracket."
              : "No encounters match. Sync from Challonge or create the first one."
          }
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">{row.original.name}</p>
              <p className="truncate text-xs text-muted-foreground">
                {encounterScopeLabel(row.original)} · R{row.original.round} ·{" "}
                <span className="font-mono tabular-nums">
                  {row.original.score.home}&ndash;{row.original.score.away}
                </span>
              </p>
              <p className="text-xs text-muted-foreground">
                {row.original.status} · {row.original.has_logs ? "logs" : "no logs"}
              </p>
            </div>
          )}
          queryKey={(page, search, pageSize, sortField, sortDir) => [
            "encounters",
            scopeTournamentId,
            page,
            search,
            pageSize,
            sortField,
            sortDir,
            { stage: stageFilter, group: groupFilter, status: statusFilter, has_logs: logsFilter }
          ]}
          queryFn={async (page, search, pageSize, sortField, sortDir) => {
            const result = await encounterService.getAll(
              page,
              search,
              scopeTournamentId,
              pageSize,
              sortField,
              sortDir,
              undefined,
              {
                stage_id: stageFilter ? Number(stageFilter) : null,
                stage_item_id: groupFilter ? Number(groupFilter) : null,
                status: statusFilter || null,
                has_logs: logsFilter ? logsFilter === "true" : null
              }
            );
            // The inspector pages through the rows currently on screen, and the
            // table owns the fetch, so this is where that page is observed.
            setPageRows(result.results);
            return result;
          }}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? `Encounter #${openRow.id}` : ""}
        subtitle={
          openRow
            ? `${openRow.tournament?.name ?? "Unknown tournament"} · ${encounterScopeLabel(openRow)} · ${bracketRoundLabelEn(openRow.round, UNKNOWN_ROUND_SHAPE)}`
            : undefined
        }
        onPrev={openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined}
        onNext={
          openIndex >= 0 && openIndex < pageRows.length - 1
            ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
            : undefined
        }
        actions={
          openRow ? (
            <EncounterInspectorActions
              encounter={openRow}
              workspaceId={workspaceId}
              canUpdate={canUpdate}
              reportsHref={reportsHref}
              onEdit={form.openEdit}
              onUploaded={invalidate}
            />
          ) : null
        }
      >
        {openRow ? (
          <EncounterInspectorPanel encounter={openRow} workspaceId={workspaceId} />
        ) : null}
      </Inspector>

      <EntityFormDialog
        open={form.mode != null}
        onOpenChange={(next) => {
          if (!next) form.close();
        }}
        title={form.mode === "edit" ? "Edit encounter" : "Create encounter"}
        description="Create or update a tournament encounter."
        isSubmitting={form.isSaving}
        submittingLabel={form.mode === "edit" ? "Updating encounter…" : "Creating encounter…"}
        errorMessage={form.error}
        isDirty={form.isDirty}
        onSubmit={(event) => {
          event.preventDefault();
          form.submit();
        }}
      >
        <EncounterForm
          mode={form.mode === "edit" ? "edit" : "create"}
          value={form.value}
          onChange={form.setValue}
          stages={stages}
          teams={teams}
        />
      </EntityFormDialog>

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: "Delete encounter",
          description: `Deleting “${pendingDelete?.name ?? "this encounter"}” removes the encounter and everything recorded under it. This cannot be undone.`,
          confirmLabel: "Delete encounter",
          tone: "danger",
          cascade: ["All matches in this encounter", "Attached match statistics and logs"]
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
