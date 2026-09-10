"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, RefreshCw, Trash2, Trophy } from "lucide-react";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { StandingsTiesPanel } from "@/components/admin/StandingsTiesPanel";
import { AdminFilterBar } from "@/components/admin/kit/AdminFilterBar";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
import { createKebabColumn } from "@/components/admin/kit/kebab-column";
import { useAdminFilters, type FilterDef } from "@/components/admin/kit/useAdminFilters";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam
} from "@/components/admin/tournament-filter";
import TeamName from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NumberInput } from "@/components/ui/number-input";
import { getTournamentWorkspaceQueryKeys, invalidateTournamentWorkspace } from "@/app/admin/tournaments/[id]/components/tournamentWorkspace.queryKeys";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import { formatTiebreakOrder } from "@/lib/tiebreakers";
import adminService from "@/services/admin.service";
import tournamentService from "@/services/tournament.service";
import type { StandingUpdateInput } from "@/types/admin.types";
import type { Standings } from "@/types/tournament.types";
import { EmptyNote } from "@/components/admin/kit/EmptyNote";

const PAGE_SIZE = 25;

const EMPTY_FORM: StandingUpdateInput = {
  points: 0,
  win: 0,
  draw: 0,
  lose: 0,
  buchholz: 0,
  tb: 0
};

function standingFormOf(standing: Standings | null): StandingUpdateInput {
  if (!standing) return { ...EMPTY_FORM };
  return {
    points: standing.points,
    win: standing.win,
    draw: standing.draw,
    lose: standing.lose,
    buchholz: standing.buchholz ?? 0,
    tb: standing.tb ?? 0
  };
}

/** The stage or stage item a standings row was computed for. */
function standingScopeLabel(standing: Standings): string {
  return standing.stage_item?.name ?? standing.stage?.name ?? "Unassigned";
}

/**
 * The standings table, for one tournament or for a tournament picked with a
 * chip.
 *
 * Standings are computed per tournament, so there is no workspace-wide table to
 * show: unscoped, this asks which tournament rather than inventing a merged
 * ranking that would mean nothing. The rows come back whole, which is why the
 * table runs in client mode — search, sort and paging are local and cost no
 * refetch.
 */
export function StandingsBrowser({
  tournamentId,
  workspaceId
}: Readonly<{
  /** `null` = the tournament comes from the `tournament` chip. */
  tournamentId: number | null;
  workspaceId: number | null;
}>) {
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const { searchParams } = useQueryParams({ resetOnChange: [] });

  const canUpdate = canAccessPermission("standing.update", workspaceId);
  const canDelete = canAccessPermission("standing.delete", workspaceId);

  const [editing, setEditing] = useState<Standings | null>(null);
  const [form, setForm] = useState<StandingUpdateInput>({ ...EMPTY_FORM });
  const [pendingDelete, setPendingDelete] = useState<Standings | null>(null);
  const [recalculateOpen, setRecalculateOpen] = useState(false);

  const chipTournamentId = parseTournamentQueryParam(
    searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null
  );
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const tournamentsQuery = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null),
    enabled: tournamentId == null
  });

  const tournamentQuery = useQuery({
    queryKey: ["admin", "tournament", scopeTournamentId],
    queryFn: () => adminService.getTournament(scopeTournamentId!),
    enabled: scopeTournamentId != null
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
    queryKey: ["admin", "stages", scopeTournamentId],
    queryFn: () => adminService.getStages(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });
  const stageList = stagesQuery.data ?? [];
  const stageItems = stageList.flatMap((stage) => stage.items);

  const defs = useMemo<FilterDef[]>(() => {
    const list: FilterDef[] = [];
    if (tournamentId == null) {
      list.push({
        key: TOURNAMENT_QUERY_PARAM,
        label: "Tournament",
        kind: "single",
        options: (tournamentsQuery.data?.results ?? []).map((entry) => ({
          value: String(entry.id),
          label: entry.name
        }))
      });
    }
    if (stageList.length > 0) {
      list.push({
        key: "stage",
        label: "Stage",
        kind: "single",
        options: stageList.map((stage) => ({ value: String(stage.id), label: stage.name }))
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
    return list;
  }, [tournamentId, tournamentsQuery.data, stageList, stageItems]);

  const filters = useAdminFilters(defs);
  const stageFilter = String(filters.values.stage ?? "");
  const groupFilter = String(filters.values.group ?? "");

  const rows = useMemo(() => {
    let scoped = standings;
    if (stageFilter) {
      scoped = scoped.filter((standing) => String(standing.stage_id ?? "") === stageFilter);
    }
    if (groupFilter) {
      scoped = scoped.filter((standing) => String(standing.stage_item_id ?? "") === groupFilter);
    }
    return scoped;
  }, [standings, stageFilter, groupFilter]);

  // Whatever tie-break order the scoped rows were actually ranked by, so the
  // sentence under the table describes these rows and not the tournament's
  // default profile.
  const tiebreakOrder = rows[0]?.tiebreak_order ?? null;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["standings"] });
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
      notify.success("Standing updated");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (standingId: number) => adminService.deleteStanding(standingId),
    onSuccess: () => {
      invalidate();
      setPendingDelete(null);
      notify.success("Standing deleted");
    }
  });

  const recalculateMutation = useMutation({
    mutationFn: () => adminService.recalculateStandings(scopeTournamentId!),
    onSuccess: () => {
      invalidate();
      setRecalculateOpen(false);
      notify.success("Standings recalculated");
    }
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncEncountersFromChallonge(scopeTournamentId!),
    onSuccess: () => {
      invalidate();
      notify.success("Results synced from Challonge");
    }
  });

  const columns = useMemo<ColumnDef<Standings>[]>(
    () => [
      {
        accessorKey: "position",
        header: "#",
        size: 72,
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            {row.original.position === 1 ? (
              <Trophy aria-hidden className="size-4 text-warning" />
            ) : null}
            <span className="font-bold tabular-nums">{row.original.position}</span>
          </div>
        )
      },
      {
        accessorKey: "team",
        header: "Team",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.team ? (
            <TeamName team={row.original.team} size="xs" nameClassName="font-medium" />
          ) : (
            "—"
          )
      },
      {
        id: "scope",
        header: "Stage",
        enableSorting: false,
        cell: ({ row }) => <span className="text-sm">{standingScopeLabel(row.original)}</span>
      },
      {
        accessorKey: "matches",
        header: "MP",
        size: 72,
        cell: ({ row }) => <span className="tabular-nums">{row.original.matches}</span>
      },
      {
        accessorKey: "win",
        header: "W",
        size: 64,
        cell: ({ row }) => <span className="tabular-nums text-success">{row.original.win}</span>
      },
      {
        accessorKey: "draw",
        header: "D",
        size: 64,
        cell: ({ row }) => <span className="tabular-nums text-warning">{row.original.draw}</span>
      },
      {
        accessorKey: "lose",
        header: "L",
        size: 64,
        cell: ({ row }) => <span className="tabular-nums text-danger">{row.original.lose}</span>
      },
      {
        accessorKey: "points",
        header: "Pts",
        size: 80,
        cell: ({ row }) => (
          <span className="font-bold tabular-nums">{row.original.points.toFixed(1)}</span>
        )
      },
      {
        accessorKey: "buchholz",
        header: "BH",
        size: 110,
        // Median and full are separate tiebreakers, and a lone number reads as
        // whichever one the organizer assumes. Show the pair, matching the
        // public table.
        cell: ({ row }) => (
          <span className="text-sm tabular-nums" title="Median / full Buchholz">
            {row.original.buchholz == null
              ? "—"
              : row.original.full_buchholz == null
                ? row.original.buchholz.toFixed(2)
                : `${row.original.buchholz.toFixed(2)} / ${row.original.full_buchholz.toFixed(2)}`}
          </span>
        )
      },
      {
        accessorKey: "tb",
        header: "TB",
        size: 72,
        cell: ({ row }) => (
          <span className="text-sm tabular-nums">{row.original.tb != null ? row.original.tb : "—"}</span>
        )
      },
      createKebabColumn<Standings>(
        (row) => [
          {
            label: "Edit standing",
            icon: Pencil,
            hidden: !canUpdate,
            onSelect: () => {
              updateMutation.reset();
              setEditing(row);
              setForm(standingFormOf(row));
            }
          },
          {
            label: "Delete standing",
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => setPendingDelete(row)
          }
        ],
        { rowLabel: (row) => `standing for ${row.team?.name ?? "team"}` }
      )
    ],
    [canUpdate, canDelete, updateMutation]
  );

  if (workspaceId == null) {
    return (
      <EmptyNote>
        Standings are scoped to a workspace. Pick one to see a ranking table.
      </EmptyNote>
    );
  }

  const canRecalculate = canUpdate && scopeTournamentId != null;

  return (
    <div className="space-y-3">
      {scopeTournamentId != null ? (
        <StandingsTiesPanel
          rows={rows}
          stages={stageList}
          tournamentId={scopeTournamentId}
          canUpdate={canUpdate}
          onChanged={invalidate}
        />
      ) : null}

      <AdminDataTable<Standings>
        rows={rows}
        isLoading={standingsQuery.isLoading}
        columns={columns}
        initialPageSize={PAGE_SIZE}
        searchPlaceholder="Search by team name…"
        filterKey={filters.filterKey}
        getRowId={(row) => String(row.id)}
        toolbar={
          <AdminFilterBar
            defs={defs}
            filters={filters}
            pinned={
              tournamentId != null
                ? [
                    {
                      key: TOURNAMENT_QUERY_PARAM,
                      label: `Tournament: ${tournamentQuery.data?.name ?? `#${tournamentId}`}`
                    }
                  ]
                : undefined
            }
            trailing={
              <>
                {canRecalculate ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={recalculateMutation.isPending}
                    onClick={() => setRecalculateOpen(true)}
                  >
                    <RefreshCw aria-hidden className="size-4" />
                    Recalculate
                  </Button>
                ) : null}
                {canAccessPermission("challonge.update", workspaceId) &&
                scopeTournamentId != null ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={syncMutation.isPending}
                    onClick={() => syncMutation.mutate()}
                  >
                    <RefreshCw aria-hidden className="size-4" />
                    Sync Challonge
                  </Button>
                ) : null}
              </>
            }
          />
        }
        emptyMessage={
          scopeTournamentId == null
            ? "Standings are computed per tournament. Pick one to see its table."
            : "No standings yet. Recalculate to build them from encounter results."
        }
        onRowDoubleClick={
          canUpdate
            ? (row) => {
                updateMutation.reset();
                setEditing(row.original);
                setForm(standingFormOf(row.original));
              }
            : undefined
        }
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">
              <span className="tabular-nums">{row.original.position}. </span>
              {row.original.team?.name ?? "Unknown team"}
            </p>
            <p className="text-xs tabular-nums text-muted-foreground">
              {row.original.win}W · {row.original.draw}D · {row.original.lose}L ·{" "}
              {row.original.points.toFixed(1)} pts
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {standingScopeLabel(row.original)}
            </p>
          </div>
        )}
      />

      {tiebreakOrder && tiebreakOrder.length > 0 ? (
        <p className="text-sm text-muted-foreground">
          Tiebreakers:{" "}
          <span className="font-medium text-foreground">
            {formatTiebreakOrder(tiebreakOrder)}
          </span>
        </p>
      ) : null}

      <EntityFormDialog
        open={editing != null}
        onOpenChange={(next) => {
          if (!next) setEditing(null);
        }}
        title="Edit standing"
        description="Adjust a stored standings row manually. Position is not editable here — every row is rebuilt from scratch on each recalculation, so use the Unresolved ties panel to set an order that survives."
        isSubmitting={updateMutation.isPending}
        submittingLabel="Updating standing…"
        errorMessage={
          updateMutation.isError
            ? `Could not update the standing. ${updateMutation.error.message}`
            : undefined
        }
        isDirty={editing != null && hasUnsavedChanges(form, standingFormOf(editing))}
        onSubmit={(event) => {
          event.preventDefault();
          if (editing) updateMutation.mutate({ id: editing.id, data: form });
        }}
      >
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label htmlFor="standing-points">Points</Label>
            <NumberInput
              id="standing-points"
              min={0}
              value={form.points ?? 0}
              onValueChange={(next) => setForm({ ...form, points: next ?? 0 })}
            />
          </div>
          <div>
            <Label htmlFor="standing-win">Wins</Label>
            <NumberInput
              id="standing-win"
              integer
              min={0}
              value={form.win ?? 0}
              onValueChange={(next) => setForm({ ...form, win: next ?? 0 })}
            />
          </div>
          <div>
            <Label htmlFor="standing-draw">Draws</Label>
            <NumberInput
              id="standing-draw"
              integer
              min={0}
              value={form.draw ?? 0}
              onValueChange={(next) => setForm({ ...form, draw: next ?? 0 })}
            />
          </div>
          <div>
            <Label htmlFor="standing-lose">Losses</Label>
            <NumberInput
              id="standing-lose"
              integer
              min={0}
              value={form.lose ?? 0}
              onValueChange={(next) => setForm({ ...form, lose: next ?? 0 })}
            />
          </div>
          <div>
            <Label htmlFor="standing-buchholz">Buchholz (median)</Label>
            <NumberInput
              id="standing-buchholz"
              value={form.buchholz ?? 0}
              onValueChange={(next) => setForm({ ...form, buchholz: next ?? 0 })}
            />
          </div>
          <div>
            <Label htmlFor="standing-tb">Head-to-head (TB)</Label>
            <NumberInput
              id="standing-tb"
              integer
              min={0}
              value={form.tb ?? 0}
              onValueChange={(next) => setForm({ ...form, tb: next ?? 0 })}
            />
          </div>
        </div>
      </EntityFormDialog>

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: "Delete standing",
          description: `Deleting the row for “${pendingDelete?.team?.name ?? "this team"}” removes it from the table. Recalculating rebuilds it from encounter results.`,
          confirmLabel: "Delete standing",
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
          title: "Recalculate standings?",
          description:
            "Every standings row for this tournament is rebuilt from encounter results. Manual adjustments are overwritten.",
          confirmLabel: "Recalculate",
          tone: "warning"
        }}
        onConfirm={() => recalculateMutation.mutate()}
      />
    </div>
  );
}
