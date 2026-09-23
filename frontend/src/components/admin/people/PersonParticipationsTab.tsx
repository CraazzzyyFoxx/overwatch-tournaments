"use client";

import { useCallback, useMemo, useState } from "react";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeftRight, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";

import { AdminDataTable, adminColumnMeta, createKebabColumn } from "@/components/data-table";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import {
  PlayerForm,
  emptyPlayerForm,
  playerCreatePayload,
  playerFormError,
  playerFormOf,
  playerUpdatePayload,
  type PlayerFormMode,
  type PlayerFormState
} from "@/components/admin/people/PlayerForm";
import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { PageStateCard } from "@/components/ui/page-state-card";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import { normalizePlayerRole } from "@/lib/roster/player-role";
import adminService from "@/services/admin.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import userService from "@/services/user.service";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { formatSubRoleLabel } from "@/utils/player";

/** One tournament this person played, flattened to the roster row that is them. */
interface ParticipationRow {
  /** `players.id` — the roster row, and this table's identity. */
  id: number;
  name: string;
  role: string | null;
  sub_role: string | null;
  rank: number;
  division: number;
  is_newcomer: boolean;
  is_substitution: boolean;
  tournament_id: number;
  tournament_name: string;
  team_id: number;
  team_name: string;
  division_grid_version: DivisionGridVersion | null;
}

/**
 * Every tournament this person has played, and the roster row they played as.
 *
 * This is the old `/admin/players` table with its scope fixed to one person:
 * the cross-tournament list existed only because there was nowhere else to see
 * a career, and a career belongs on the person's card.
 */
export function PersonParticipationsTab({
  personId,
  personName,
  workspaceId
}: Readonly<{ personId: number; personName: string; workspaceId: number | null }>) {
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const canCreate = canAccessPermission("player.create", workspaceId);
  const canUpdate = canAccessPermission("player.update", workspaceId);
  const canDelete = canAccessPermission("player.delete", workspaceId);

  const [formMode, setFormMode] = useState<PlayerFormMode | null>(null);
  const [editing, setEditing] = useState<ParticipationRow | null>(null);
  const [form, setForm] = useState<PlayerFormState>(emptyPlayerForm(personId, null));
  const [formInitial, setFormInitial] = useState<PlayerFormState>(emptyPlayerForm(personId, null));
  const [saveError, setSaveError] = useState<string | undefined>();
  const [pendingDelete, setPendingDelete] = useState<ParticipationRow | null>(null);

  const participationsQuery = useQuery({
    queryKey: ["user-tournaments", personId, workspaceId],
    queryFn: () => userService.getUserTournaments(personId, workspaceId)
  });

  // Sub-roles are a workspace catalog, and the participation list is already
  // scoped to the active workspace, so one fetch covers every row.
  const subRolesQuery = useQuery({
    queryKey: ["player-sub-roles", workspaceId],
    queryFn: () => adminService.getPlayerSubRoles({ workspace_id: workspaceId! }),
    enabled: workspaceId != null
  });

  const tournamentsQuery = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null),
    enabled: canCreate
  });

  const teamsQuery = useQuery({
    queryKey: ["teams", form.tournament_id || null],
    queryFn: () => teamService.getAll({ tournamentId: form.tournament_id }),
    enabled: formMode === "create" && form.tournament_id > 0
  });

  const rows = useMemo<ParticipationRow[]>(
    () =>
      (participationsQuery.data ?? []).flatMap((entry) => {
        const player = entry.players.find((candidate) => candidate.user_id === personId);
        if (!player) return [];
        return [
          {
            id: player.id,
            name: player.name,
            role: player.role,
            sub_role: player.sub_role,
            rank: player.rank,
            division: player.division,
            is_newcomer: player.is_newcomer,
            is_substitution: player.is_substitution,
            tournament_id: entry.id,
            tournament_name: entry.name,
            team_id: entry.team_id,
            team_name: entry.team,
            division_grid_version: entry.division_grid_version
          }
        ];
      }),
    [participationsQuery.data, personId]
  );

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["user-tournaments", personId] });
    void queryClient.invalidateQueries({ queryKey: ["teams"] });
  };

  const closeForm = () => {
    setFormMode(null);
    setEditing(null);
    setSaveError(undefined);
  };

  const saveMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: (payload: PlayerFormState) =>
      editing
        ? adminService.updatePlayer(editing.id, playerUpdatePayload(payload))
        : adminService.createPlayer(playerCreatePayload(payload)),
    onSuccess: () => {
      const created = editing == null;
      invalidate();
      closeForm();
      notify.success(created ? "Participation added" : "Participation updated");
    },
    onError: (error: Error) => setSaveError(`Could not save the participation. ${error.message}`)
  });

  const deleteMutation = useMutation({
    mutationFn: (playerId: number) => adminService.deletePlayer(playerId),
    onSuccess: () => {
      invalidate();
      setPendingDelete(null);
      notify.success("Participation removed");
    }
  });

  // `saveMutation` is rebuilt on every state transition; `reset` is not, so the
  // memoised `openEdit` below hangs on the callback instead of the container.
  const { reset: resetSaveMutation } = saveMutation;

  const openCreate = () => {
    const blank = emptyPlayerForm(personId, null);
    blank.name = personName;
    resetSaveMutation();
    setSaveError(undefined);
    setEditing(null);
    setForm(blank);
    setFormInitial(blank);
    setFormMode("create");
  };

  // The kebab column closes over this, so the column memo has to depend on it —
  // which means it needs an identity that only moves when its inputs do. Every
  // other name it touches is a `useState` setter (stable by contract).
  const openEdit = useCallback(
    (row: ParticipationRow) => {
      const initial = playerFormOf(row, personId);
      resetSaveMutation();
      setSaveError(undefined);
      setEditing(row);
      setForm(initial);
      setFormInitial(initial);
      setFormMode("edit");
    },
    [personId, resetSaveMutation]
  );

  const columns = useMemo<ColumnDef<ParticipationRow>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        size: 200,
        meta: adminColumnMeta<ParticipationRow>({
          sticky: true,
          searchValue: (row) => row.name
        }),
        cell: ({ row }) => <div className="font-medium">{row.original.name}</div>
      },
      {
        accessorKey: "team_name",
        header: "Team",
        enableSorting: false,
        meta: adminColumnMeta<ParticipationRow>({ searchValue: (row) => row.team_name }),
        cell: ({ row }) => (
          <Link
            className="text-sm underline-offset-4 hover:underline"
            href={`/admin/teams/${row.original.team_id}`}
          >
            {row.original.team_name}
          </Link>
        )
      },
      {
        accessorKey: "tournament_name",
        header: "Tournament",
        enableSorting: false,
        meta: adminColumnMeta<ParticipationRow>({ searchValue: (row) => row.tournament_name }),
        cell: ({ row }) => (
          <Link
            className="text-sm text-muted-foreground underline-offset-4 hover:underline"
            href={`/admin/tournaments/${row.original.tournament_id}/overview`}
          >
            {row.original.tournament_name}
          </Link>
        )
      },
      {
        accessorKey: "role",
        header: "Role",
        cell: ({ row }) => (
          <div className="flex items-center" title={normalizePlayerRole(row.original.role)}>
            <PlayerRoleIcon role={normalizePlayerRole(row.original.role)} size={18} />
          </div>
        )
      },
      {
        // Division is derived from rank, so the two ride in one column and sort
        // by the finer of the pair.
        accessorKey: "rank",
        header: "Div · Rank",
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <DivisionIcon
              division={row.original.division}
              tournamentGrid={row.original.division_grid_version}
              width={28}
              height={28}
            />
            <span className="tabular-nums">{row.original.rank}</span>
          </div>
        )
      },
      {
        accessorKey: "sub_role",
        header: "Sub-role",
        cell: ({ row }) => <div>{formatSubRoleLabel(row.original.sub_role) ?? "—"}</div>
      },
      {
        id: "flags",
        header: "Flags",
        enableSorting: false,
        meta: adminColumnMeta({ align: "center" }),
        cell: ({ row }) => (
          <div className="flex justify-center gap-1">
            {row.original.is_newcomer && (
              <StatusIcon icon={Sparkles} label="Newcomer" variant="warning" />
            )}
            {row.original.is_substitution && (
              <StatusIcon icon={ArrowLeftRight} label="Substitute" variant="info" />
            )}
          </div>
        )
      },
      createKebabColumn<ParticipationRow>(
        (row) => [
          {
            label: "Edit participation",
            icon: Pencil,
            hidden: !canUpdate,
            onSelect: () => openEdit(row)
          },
          {
            label: "Remove participation",
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => setPendingDelete(row)
          }
        ],
        { rowLabel: (row) => `${row.name} in ${row.tournament_name}` }
      )
    ],
    // `openEdit` was missing here: the kebab's "Edit participation" called
    // whichever closure the first render happened to build. It carries
    // `personId` itself, so the column list no longer needs it separately.
    [canUpdate, canDelete, openEdit]
  );

  if (participationsQuery.isError) {
    return (
      <PageStateCard
        state="error"
        title="Could not load participations"
        onAction={() => void participationsQuery.refetch()}
        actionLabel="Try again"
      />
    );
  }

  return (
    <div className="space-y-4">
      <AdminDataTable<ParticipationRow>
        rows={rows}
        isLoading={participationsQuery.isLoading}
        columns={columns}
        initialPageSize={20}
        getRowId={(row) => String(row.id)}
        searchPlaceholder="Search participations…"
        emptyMessage="This person has not played a tournament in this workspace yet."
        actions={
          canCreate ? (
            <Button size="sm" onClick={openCreate}>
              <Plus aria-hidden className="size-4" />
              Add participation
            </Button>
          ) : null
        }
        onRowDoubleClick={canUpdate ? (row) => openEdit(row.original) : undefined}
        renderMobileCard={(row) => (
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{row.original.name}</p>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.team_name} · {row.original.tournament_name}
            </p>
            <p className="text-xs text-muted-foreground">
              {normalizePlayerRole(row.original.role)} ·{" "}
              <span className="tabular-nums">{row.original.rank}</span>
              {row.original.sub_role ? ` · ${formatSubRoleLabel(row.original.sub_role)}` : ""}
            </p>
          </div>
        )}
      />

      <EntityFormDialog
        open={formMode != null}
        onOpenChange={(next) => {
          if (!next) closeForm();
        }}
        title={formMode === "edit" ? "Edit participation" : "Add participation"}
        description={
          formMode === "edit"
            ? `Update how ${personName} played this tournament.`
            : `Add ${personName} to a team in one tournament.`
        }
        isSubmitting={saveMutation.isPending}
        submittingLabel={formMode === "edit" ? "Updating…" : "Adding…"}
        errorMessage={saveError}
        isDirty={formMode != null && hasUnsavedChanges(form, formInitial)}
        onSubmit={(event) => {
          event.preventDefault();
          const invalid = playerFormError(form, formMode ?? "edit");
          if (invalid) {
            setSaveError(invalid);
            return;
          }
          saveMutation.mutate(form);
        }}
      >
        <PlayerForm
          mode={formMode === "edit" ? "edit" : "create"}
          value={form}
          onChange={setForm}
          subRoles={subRolesQuery.data}
          divisionGrid={
            editing?.division_grid_version ??
            (tournamentsQuery.data?.results.find(
              (tournament) => tournament.id === form.tournament_id
            )?.division_grid_version ??
              null)
          }
          tournaments={tournamentsQuery.data?.results ?? []}
          teams={teamsQuery.data?.results ?? []}
        />
      </EntityFormDialog>

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: "Remove participation",
          description: `Removing “${pendingDelete?.name ?? "this player"}” from ${pendingDelete?.tournament_name ?? "the tournament"} deletes the roster row along with its match statistics. This cannot be undone.`,
          confirmLabel: "Remove participation",
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
