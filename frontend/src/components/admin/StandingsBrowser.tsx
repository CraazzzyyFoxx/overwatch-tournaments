"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock } from "lucide-react";

import { DataTable } from "@/components/data-table";
import { StandingsArrangeBoard } from "@/components/admin/StandingsArrangeBoard";
import { FilterBar } from "@/components/kit/FilterBar";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam
} from "@/components/admin/tournament-filter";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Spinner } from "@/components/ui/spinner";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { getTournamentWorkspaceQueryKeys, invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { formatTiebreakOrder } from "@/lib/tournament/tiebreakers";
import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import type { StandingUpdateInput } from "@/types/admin.types";
import type { Standings } from "@/types/tournament.types";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

import { StandingEditDialog } from "./standings/StandingEditDialog";
import { standingFilterDefs } from "./standings/filters";
import { EMPTY_FORM, standingFormOf, standingScopeLabel } from "./standings/model";
import { useStandingsColumns } from "./standings/useStandingsColumns";

const PAGE_SIZE = 25;

/**
 * The standings table, for one tournament or for a tournament picked with a
 * chip.
 *
 * Standings are computed per tournament, so there is no workspace-wide table to
 * show: unscoped, this asks which tournament rather than inventing a merged
 * ranking that would mean nothing. The rows come back whole, which is why the
 * table runs in client mode — search, sort and paging are local and cost no
 * refetch.
 *
 * `stageId` scopes it to one stage — the Bracket tab's stage editor shows its
 * own table there, so the stage is a pinned fact rather than a filter.
 */
export function StandingsBrowser({
  tournamentId,
  workspaceId,
  stageId
}: Readonly<{
  /** `null` = the tournament comes from the `tournament` chip. */
  tournamentId: number | null;
  workspaceId: number | null;
  /** Set = only this stage's rows, and no Stage filter to widen it again. */
  stageId?: number;
}>) {
  const t = useTranslations("adminTournaments.standings");
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const { searchParams } = useQueryParams({ resetOnChange: [] });

  const canUpdate = canAccessPermission("standing.update", workspaceId);
  const canDelete = canAccessPermission("standing.delete", workspaceId);

  const [editing, setEditing] = useState<Standings | null>(null);
  const [form, setForm] = useState<StandingUpdateInput>({ ...EMPTY_FORM });
  const [pendingDelete, setPendingDelete] = useState<Standings | null>(null);
  const [recalculateOpen, setRecalculateOpen] = useState(false);
  const [view, setView] = useState<"table" | "arrange">("table");

  const chipTournamentId = parseTournamentQueryParam(
    searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null
  );
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll(null),
    enabled: tournamentId == null
  });

  // The hub shell already holds this exact key, so mounting the tab costs no
  // request; realtime addresses it too (`tournament.standings`).
  const standingsQuery = useQuery({
    queryKey:
      scopeTournamentId != null
        ? getTournamentWorkspaceQueryKeys(scopeTournamentId).standings
        : ["admin", "tournament", null, "standings"],
    queryFn: () =>
      tournamentService.getStandings(scopeTournamentId!, {
        includeMatchesHistory: false,
        includeTeamGroup: false
      }),
    enabled: scopeTournamentId != null
  });

  const standings = standingsQuery.data ?? [];

  const stagesQuery = useQuery({
    queryKey: adminQueryKeys.stages(scopeTournamentId),
    queryFn: () => adminService.getStages(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });
  const stageList = stagesQuery.data ?? [];
  const scopedStage = stageId != null ? stageList.find((stage) => stage.id === stageId) : undefined;
  // Scoped to one stage, only ITS groups are worth filtering by.
  const stageItems = (stageId != null ? (scopedStage ? [scopedStage] : []) : stageList).flatMap(
    (stage) => stage.items
  );

  const defs = standingFilterDefs({
    tournamentId,
    stageId,
    tournaments: tournamentsQuery.data?.results ?? [],
    stages: stageList,
    stageItems,
    t
  });

  const filters = useFilters(defs);
  const stageFilter = String(filters.values.stage ?? "");
  const groupFilter = String(filters.values.group ?? "");

  const rows = useMemo(() => {
    let scoped = stageId != null ? standings.filter((row) => row.stage_id === stageId) : standings;
    if (stageFilter) {
      scoped = scoped.filter((standing) => String(standing.stage_id ?? "") === stageFilter);
    }
    if (groupFilter) {
      scoped = scoped.filter((standing) => String(standing.stage_item_id ?? "") === groupFilter);
    }
    return scoped;
  }, [standings, stageId, stageFilter, groupFilter]);

  // Whatever tie-break order the scoped rows were actually ranked by, so the
  // sentence under the table describes these rows and not the tournament's
  // default profile.
  const tiebreakOrder = rows[0]?.tiebreak_order ?? null;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.standingsAll() });
    if (scopeTournamentId != null) {
      invalidateTournamentWorkspace(queryClient, scopeTournamentId, workspaceId);
    }
  };

  const updateMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: (payload: { id: number; data: StandingUpdateInput }) =>
      adminService.updateStanding(payload.id, payload.data),
    onSuccess: () => {
      invalidate();
      setEditing(null);
      notify.success(t("updated"));
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (standingId: number) => adminService.deleteStanding(standingId),
    onSuccess: () => {
      invalidate();
      setPendingDelete(null);
      notify.success(t("deleted"));
    }
  });

  const recalculateMutation = useMutation({
    mutationFn: () => adminService.recalculateStandings(scopeTournamentId!),
    onSuccess: () => {
      invalidate();
      setRecalculateOpen(false);
      notify.success(t("recalculated"));
    }
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncEncountersFromChallonge(scopeTournamentId!),
    onSuccess: () => {
      invalidate();
      notify.success(t("synced"));
    }
  });

  // `updateMutation` is rebuilt on every state transition; `reset` is not, so the
  // memoised `openEdit` hangs on the callback instead of the container.
  const { reset: resetUpdateMutation } = updateMutation;

  // The kebab column closes over this, so it needs an identity that only moves
  // when its inputs do; the two setters never do.
  const openEdit = useCallback(
    (standing: Standings) => {
      resetUpdateMutation();
      setEditing(standing);
      setForm(standingFormOf(standing));
    },
    [resetUpdateMutation, setEditing, setForm]
  );

  const columns = useStandingsColumns({
    canUpdate,
    canDelete,
    stageId,
    scopedStage,
    onEdit: openEdit,
    onDelete: setPendingDelete
  });

  if (workspaceId == null) {
    return (
      <EmptyNote>
        {t("workspaceRequired")}
      </EmptyNote>
    );
  }

  const failedQuery = standingsQuery.isError
    ? standingsQuery
    : stagesQuery.isError
      ? stagesQuery
      : null;
  if (failedQuery) {
    return <PageStateCard state="error" onAction={() => void failedQuery.refetch()} />;
  }

  const canRecalculate = canUpdate && scopeTournamentId != null;
  const canSync = canAccessPermission("challonge.update", workspaceId) && scopeTournamentId != null;
  const arranging = view === "arrange" && scopeTournamentId != null;

  const toolbar = <FilterBar defs={defs} filters={filters} />;

  return (
    <div className="space-y-3">
      {/* Shared by both views, above the filter surface: the switch between
          them, and the actions on the whole table — the arrange view has no
          table toolbar to host them. Only with a tournament scoped: without
          one there is nothing to arrange, recalculate or sync. */}
      {scopeTournamentId != null ? (
        <div className="flex flex-wrap items-center gap-2">
          <ToggleGroup
            type="single"
            variant="pill"
            size="sm"
            value={view}
            onValueChange={(next) => {
              if (next) setView(next as "table" | "arrange");
            }}
            aria-label={t("view")}
          >
            <ToggleGroupItem value="table">{t("table")}</ToggleGroupItem>
            <ToggleGroupItem value="arrange">{t("arrange")}</ToggleGroupItem>
          </ToggleGroup>
          <div className="ml-auto flex flex-wrap gap-2">
            {canRecalculate ? (
              <Button
                variant="outline"
                size="sm"
                disabled={recalculateMutation.isPending}
                onClick={() => setRecalculateOpen(true)}
              >
                {t("recalculate")}
              </Button>
            ) : null}
            {canSync ? (
              <Button
                variant="outline"
                size="sm"
                disabled={syncMutation.isPending}
                onClick={() => syncMutation.mutate()}
              >
                {syncMutation.isPending ? <Spinner /> : null}
                {t("sync")}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
      {arranging ? (
        <>
          {toolbar}
          <StandingsArrangeBoard
            rows={rows}
            stages={stageList}
            canUpdate={canUpdate}
            onChanged={invalidate}
          />
        </>
      ) : (
        <DataTable<Standings>
          rows={rows}
          isLoading={standingsQuery.isLoading}
          columns={columns}
          initialPageSize={PAGE_SIZE}
          searchPlaceholder={t("searchPlaceholder")}
          filterKey={filters.filterKey}
          getRowId={(row) => String(row.id)}
          toolbar={toolbar}
          emptyMessage={
            scopeTournamentId == null
              ? t("pickTournament")
              : t("empty")
          }
          onRowDoubleClick={canUpdate ? (row) => openEdit(row.original) : undefined}
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                <span className="tabular-nums">{row.original.position}. </span>
                {row.original.is_pinned ? (
                  <>
                    <Lock aria-hidden className="mr-1 inline size-3.5" />
                    <span className="sr-only">{t("pinnedPlaceComma")}</span>
                  </>
                ) : null}
                {row.original.team?.name ?? t("unknownTeam")}
              </p>
              <p className="text-xs tabular-nums text-muted-foreground">
                {t("recordSummary", {
                  wins: row.original.win,
                  draws: row.original.draw,
                  losses: row.original.lose,
                  points: row.original.points.toFixed(1)
                })}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {standingScopeLabel(row.original, t("unassigned"))}
              </p>
            </div>
          )}
        />
      )}

      {tiebreakOrder && tiebreakOrder.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          {t.rich("tiebreakSummary", {
            value: formatTiebreakOrder(tiebreakOrder),
            valueText: (chunks) => <span className="font-medium text-foreground">{chunks}</span>
          })}
        </p>
      ) : null}

      <StandingEditDialog
        editing={editing}
        form={form}
        onFormChange={setForm}
        onClose={() => setEditing(null)}
        isSubmitting={updateMutation.isPending}
        error={updateMutation.error}
        onSave={updateMutation.mutate}
      />

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: t("delete"),
          description: t("deleteDescription", { name: pendingDelete?.team?.name ?? t("thisTeam") }),
          confirmLabel: t("delete"),
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />

      <ConfirmDialog
        open={recalculateOpen}
        onOpenChange={setRecalculateOpen}
        pending={recalculateMutation.isPending}
        intent={{
          title: t("recalculateTitle"),
          description:
            t("recalculateDescription"),
          confirmLabel: t("recalculate"),
          tone: "warning"
        }}
        onConfirm={() => recalculateMutation.mutate()}
      />
    </div>
  );
}
