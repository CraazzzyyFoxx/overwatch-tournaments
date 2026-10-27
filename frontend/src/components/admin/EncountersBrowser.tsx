"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { usePathname } from "next/navigation";
import { FileX2, Plus } from "lucide-react";

import { DataTable, type TableCommand } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { RowGameLabel, gameColumn } from "@/components/workspace/game-column";
import { EncounterForm } from "@/components/admin/EncounterForm";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import { gameFilterDefs } from "@/components/admin/game-filter";
import { hasChallongeSource } from "@/components/admin/tournament-checklist";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam,
  strandedTournamentParams,
  tournamentOptions
} from "@/components/admin/tournament-filter";
import { PageStateCard } from "@/components/ui/page-state-card";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { usePermissions } from "@/hooks/usePermissions";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { useQueryParams } from "@/hooks/useQueryParams";
import { UNKNOWN_ROUND_SHAPE } from "@/lib/bracket/round-name";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import encounterService from "@/services/encounter.service";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Encounter } from "@/types/encounter.types";
import { seatsBySlot } from "@/lib/encounter/seats";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

import { ResultStatusPill, encounterScopeLabel, encounterStatusKey } from "./encounters/EncounterCells";
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
  workspaceId,
  discipline,
  games
}: Readonly<{
  /** `null` = every tournament in the workspace, with the chip unpinned. */
  tournamentId: number | null;
  workspaceId: number | null;
  /**
   * The workspace view's Game chip (`?discipline=`, spec §6.9): `null` = every game, with a "Game" column; a code =
   * that game's encounters, filtered on the server. Absent in a tournament hub, where the tournament is the game.
   */
  discipline?: string | null;
  /** The community's games, for the Game chip; absent in a hub. */
  games?: readonly DisciplineDescriptor[];
}>) {
  const t = useTranslations("adminMatches.encounters");
  const tGame = useTranslations("common.discipline");
  const formatRound = useBracketRoundLabel();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row is on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;
  // A pre-game room opened from here hands the organizer back to this exact
  // list — chips, page and open row included, since they all live in the URL.
  const pathname = usePathname();
  const returnToQuery = searchParams?.toString() ?? "";
  const returnTo = returnToQuery ? `${pathname}?${returnToQuery}` : pathname;

  const canCreate = canAccessPermission("match.create", workspaceId);
  const canUpdate = canAccessPermission("match.update", workspaceId);
  const canDelete = canAccessPermission("match.delete", workspaceId);
  // Encounter sync hits the Challonge import endpoint, so it is gated on the
  // Challonge grant rather than on `match.*`.
  const canSync = canAccessPermission("challonge.update", workspaceId);

  const [pageRows, setPageRows] = useState<Encounter[]>([]);
  const [pendingDelete, setPendingDelete] = useState<Encounter | null>(null);

  // The tournament chip works under every game: without one it offers every tournament of the workspace. A tournament
  // pinned by the hub is the game's owner (`discipline` is absent there).
  const chipTournamentId = parseTournamentQueryParam(searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null);
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const scope = useEncounterScope({ tournamentId, scopeTournamentId, workspaceId });
  const { stages, teams } = scope;
  const chipTournamentGame = scope.tournaments.find((tournament) => tournament.id === chipTournamentId)?.discipline;

  const defs = useMemo(
    () => [
      // A game pick drops a tournament of another game, with its stage and group.
      ...gameFilterDefs(games, tGame("column"), (next) => strandedTournamentParams(chipTournamentGame, next)),
      ...encounterFilterDefs({
        tournamentId,
        tournaments: tournamentOptions(scope.tournaments, discipline ?? null),
        stages,
        stageItems: scope.stageItems,
        t: t as unknown as (key: string) => string
      })
    ],
    [games, chipTournamentGame, tournamentId, discipline, scope.tournaments, stages, scope.stageItems, t, tGame]
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
  const formScope = useEncounterScope({
    tournamentId: form.tournamentId,
    scopeTournamentId: form.tournamentId,
    workspaceId
  });

  const deleteMutation = useMutation({
    mutationFn: (encounterId: number) => adminService.deleteEncounter(encounterId),
    onSuccess: () => {
      const removed = pendingDelete;
      invalidate();
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success(t("deleted"));
    }
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncEncountersFromChallonge(scopeTournamentId!),
    onSuccess: () => {
      invalidate();
      notify.success(t("synced"));
    }
  });

  const baseColumns = useEncounterColumns({
    canUpdate,
    canDelete,
    returnTo,
    onEdit: form.openEdit,
    onDelete: setPendingDelete
  });
  const columns =
    discipline === null
      ? [baseColumns[0], gameColumn<Encounter>(tGame("column"), (row) => row.discipline), ...baseColumns.slice(1)]
      : baseColumns;

  if (workspaceId == null) {
    return <PageStateCard state="empty" description={t("scopePrompt")} />;
  }

  const challongeReady = hasChallongeSource(scope.tournament, stages);
  // Creating needs a stage to file under and two teams to seat; without them
  // the button is absent and the empty table says what is missing.
  const createReady = scopeTournamentId != null && stages.length > 0 && teams.length >= 2;
  const reportsHref =
    tournamentId != null
      ? `/admin/tournaments/${tournamentId}/matches/reports`
      : "/admin/matches?view=reports";

  const commands: TableCommand[] = [
    {
      id: "sync",
      label: t("sync"),
      hidden: !(canSync && scopeTournamentId != null && challongeReady),
      pending: syncMutation.isPending,
      disabled: syncMutation.isPending,
      onSelect: () => syncMutation.mutate()
    },
    {
      id: "create",
      label: t("create"),
      icon: Plus,
      primary: true,
      hidden: !(canCreate && createReady),
      onSelect: form.openCreate
    }
  ];

  return (
    <div
      className={cn(
        "grid items-start gap-4",
        openRow && "lg:grid-cols-[minmax(0,1fr)_380px]"
      )}
    >
      <div className="min-w-0">
        <DataTable<Encounter>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          searchPlaceholder={t("search")}
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={<FilterBar defs={defs} filters={filters} />}
          commands={commands}
          emptyMessage={
            scopeTournamentId == null
              ? t("emptyTournament")
              : canCreate && !createReady
                ? t("createNeeds")
                : t("empty")
          }
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          renderMobileCard={(row) => {
            const status = encounterStatusKey(row.original.status);
            const scopeLabel = encounterScopeLabel(row.original);
            return (
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="truncate text-sm font-medium">{row.original.name}</p>
                {discipline === null ? (
                  <RowGameLabel code={row.original.discipline} className="flex text-xs text-muted-foreground" />
                ) : null}
                <p className="truncate text-xs text-muted-foreground">
                  {scopeLabel ? `${scopeLabel} · ` : null}R{row.original.round} ·{" "}
                  <span className="tabular-nums">
                    {seatsBySlot(row.original.teams).map((seat) => seat.score).join("\u2013")}
                  </span>
                </p>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  {status && status !== "completed" ? <span>{t(status)}</span> : null}
                  <ResultStatusPill status={row.original.result_status} />
                  {row.original.has_logs ? null : <StatusIcon icon={FileX2} label={t("noLogs")} variant="muted" />}
                </div>
              </div>
            );
          }}
          queryKey={(page, search, pageSize, sortField, sortDir) => [
            "encounters",
            workspaceId,
            scopeTournamentId,
            page,
            search,
            pageSize,
            sortField,
            sortDir,
            { stage: stageFilter, group: groupFilter, status: statusFilter, has_logs: logsFilter },
            discipline ?? null
          ]}
          queryFn={(page, search, pageSize, sortField, sortDir) =>
            encounterService.getAll(
              page,
              search,
              scopeTournamentId,
              pageSize,
              sortField,
              sortDir,
              workspaceId,
              {
                stage_id: stageFilter ? Number(stageFilter) : null,
                stage_item_id: groupFilter ? Number(groupFilter) : null,
                status: statusFilter || null,
                has_logs: logsFilter ? logsFilter === "true" : null,
                discipline: discipline ?? null
              }
            )
          }
          onPageRowsChange={setPageRows}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? t("encounterNumber", { id: openRow.id }) : ""}
        subtitle={
          openRow
            ? t("detailSubtitle", {
                tournament: openRow.tournament?.name ?? t("unknownTournament"),
                scope: encounterScopeLabel(openRow),
                round: formatRound(openRow.round, UNKNOWN_ROUND_SHAPE)
              })
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
              returnTo={returnTo}
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
        title={form.mode === "edit" ? t("editTitle") : t("createTitle")}
        isSubmitting={form.isSaving}
        submittingLabel={form.mode === "edit" ? t("updating") : t("creating")}
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
          stages={formScope.stages}
          teams={formScope.teams}
        />
      </EntityFormDialog>

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: t("delete"),
          description: t("deleteDescription", { name: pendingDelete?.name ?? "" }),
          confirmLabel: t("delete"),
          tone: "danger",
          cascade: [t("allMatches"), t("attachedStats")]
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
