"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQueries, useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { ArrowLeftRight, Pencil, Plus, Sparkles, Trash2 } from "lucide-react";

import { DataTable, columnMeta, createKebabColumn } from "@craazzzyyfoxx/admin-kit/data-table";
import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
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
import { LoadErrorNote } from "@craazzzyyfoxx/admin-kit/kit/EmptyNote";
import { SettingGroup } from "@/components/kit/SettingRow";
import DivisionIcon from "@/components/DivisionIcon";
import RosterSlotGlyph from "@/components/registration/RosterSlotGlyph";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { usePermissions } from "@/hooks/usePermissions";
import { useDisciplineMetadata, useDisciplines } from "@/hooks/useDisciplineMetadata";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { hasUnsavedChanges } from "@/lib/form-change";
import { notify } from "@/lib/notify";
import { ratedDimension } from "@/lib/roster/ontology";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import adminService from "@/services/admin.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import userService from "@/services/user.service";
import type { DivisionGridVersion } from "@/types/workspace.types";
import type { UserTournamentList } from "@/types/user.types";
import { formatSubRoleLabel } from "@/lib/player";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { userQueryKeys } from "@/lib/users/query-keys";
import { roleOf, subRoleOf, type RoleRef } from "@/lib/roster/role-ref";

/** One tournament this person played, flattened to the roster row that is them. */
interface ParticipationRow {
  /** `players.id` — the roster row, and this table's identity. */
  id: number;
  name: string;
  role: RoleRef | null;
  rank: number | null;
  division: number | null;
  is_newcomer: boolean;
  is_substitution: boolean;
  tournament_id: number;
  tournament_name: string;
  workspace_id: number;
  discipline: string;
  team_id: number;
  team_name: string;
  division_grid_version: DivisionGridVersion | null;
}

/** Every installed game's career read as one list (module level: a stable `combine` keeps the merged identity). */
function mergeCareers(results: UseQueryResult<UserTournamentList>[]) {
  return {
    data: results.flatMap((result) => result.data?.results ?? []),
    gridVersions: results.flatMap((result) => result.data?.division_grid_versions ?? []),
    isError: results.some((result) => result.isError),
    isLoading: results.some((result) => result.isLoading),
    refetchFailed: () => {
      for (const result of results) if (result.isError) void result.refetch();
    }
  };
}

/**
 * A participation's role, named and drawn in the game of ITS tournament: a person's career spans games, so every row
 * reads its own owner's metadata (one cached read per game and workspace).
 */
function ParticipationRole({ row, named = false }: Readonly<{ row: ParticipationRow; named?: boolean }>) {
  const ontology = useDisciplineMetadata(row.workspace_id, row.discipline).data ?? null;
  const slotLabel = useSlotLabel(ontology);
  const code = row.role ? roleOf(row.role) : OPEN_SLOT_CODE;
  return named ? (
    <>{slotLabel(code)}</>
  ) : (
    <div className="flex items-center" title={slotLabel(code)}>
      <RosterSlotGlyph code={code} ontology={ontology} size={18} />
    </div>
  );
}

/** Newcomer and substitute are a roster row's exceptions, so each shows only when it holds. */
function ParticipationFlags({ row }: Readonly<{ row: ParticipationRow }>) {
  const t = useTranslations("adminPeople.participations");
  return (
    <>
      {row.is_newcomer ? <StatusIcon icon={Sparkles} label={t("newcomer")} variant="warning" /> : null}
      {row.is_substitution ? <StatusIcon icon={ArrowLeftRight} label={t("substitute")} variant="info" /> : null}
    </>
  );
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
  const t = useTranslations("adminPeople.participations");
  const formT = useTranslations("adminPeople.form");
  const roleT = useTranslations("common.roleOntology");
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

  // The server reads one game's career per call: every installed game's (history of a game the workspace no
  // longer runs included), merged.
  const installedQuery = useDisciplines("all");
  const careers = useQueries({
    queries: (installedQuery.data ?? []).map((game) => ({
      queryKey: userQueryKeys.tournaments(personId, workspaceId, game.code),
      queryFn: () => userService.getUserTournaments(personId, game.code, workspaceId)
    })),
    combine: mergeCareers
  });
  const participations = careers.data;
  const participationsQuery = {
    isError: installedQuery.isError || careers.isError,
    isLoading: installedQuery.isLoading || careers.isLoading,
    refetch: () => {
      void installedQuery.refetch();
      careers.refetchFailed();
    }
  };

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll(),
    enabled: canCreate
  });

  // Editing never moves a participation, so its owner is the participation's own tournament; a new one is owned
  // by the tournament picked in the form.
  const selectedOwner = editing ?? tournamentsQuery.data?.results.find(tournament => tournament.id === form.tournament_id);
  const discipline = selectedOwner?.discipline;
  const ownerWorkspaceId = selectedOwner?.workspace_id;
  const ownerScopeMissing = (editing != null || form.tournament_id > 0) && (!discipline || ownerWorkspaceId == null);
  // The form's role choices are the owner game's: the selected participation's (edit) or tournament's (create).
  const ownerMetadata = useDisciplineMetadata(ownerWorkspaceId ?? "all", ownerWorkspaceId != null ? discipline ?? null : null);
  const ontology = ownerMetadata.data ?? null;
  const ratedCode = ontology ? ratedDimension(ontology)?.code : undefined;
  const metadataFailed = ownerMetadata.isError || (ontology !== null && !ratedCode);
  const subRolesQuery = useQuery({
    queryKey: adminQueryKeys.playerSubRolesPublic(ownerWorkspaceId, discipline),
    queryFn: ({ signal }) => adminService.getPlayerSubRoles({ workspace_id: ownerWorkspaceId!, discipline: discipline! }, signal),
    enabled: formMode !== null && ownerWorkspaceId != null && Boolean(discipline)
  });

  const teamsQuery = useQuery({
    queryKey: tournamentQueryKeys.teams(form.tournament_id || null),
    queryFn: () => teamService.getAll({ tournamentId: form.tournament_id }),
    enabled: formMode === "create" && form.tournament_id > 0
  });

  const rows = useMemo<ParticipationRow[]>(
    () =>
      participations.flatMap((entry) => {
        const player = entry.players.find((candidate) => candidate.user_id === personId);
        if (!player) return [];
        return [
          {
            id: player.id,
            name: player.name,
            role: player.role,
            rank: player.rank,
            division: player.division,
            is_newcomer: player.is_newcomer,
            is_substitution: player.is_substitution,
            tournament_id: entry.id,
            tournament_name: entry.name,
            workspace_id: entry.workspace_id,
            discipline: entry.discipline,
            team_id: entry.team_id,
            team_name: entry.team,
            division_grid_version:
              careers.gridVersions.find((version) => version.id === entry.division_grid_version_id) ?? null
          }
        ];
      }),
    [participations, careers.gridVersions, personId]
  );

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: userQueryKeys.statsAll(personId) });
    void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.teamsAll() });
  };

  const closeForm = () => {
    setFormMode(null);
    setEditing(null);
    setSaveError(undefined);
  };

  const saveMutation = useMutation({
    meta: { suppressErrorToast: true },
    mutationFn: ({ state, dimension }: { state: PlayerFormState; dimension: string }) =>
      editing
        ? adminService.updatePlayer(editing.id, playerUpdatePayload(state, dimension))
        : adminService.createPlayer(playerCreatePayload(state, dimension)),
    onSuccess: () => {
      const created = editing == null;
      invalidate();
      closeForm();
      notify.success(created ? t("added") : t("updated"));
    },
    onError: (error: Error) => setSaveError(t("saveError", { message: error.message }))
  });

  const deleteMutation = useMutation({
    mutationFn: (playerId: number) => adminService.deletePlayer(playerId),
    onSuccess: () => {
      invalidate();
      setPendingDelete(null);
      notify.success(t("removed"));
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

  // The roster row is usually the person's own name; it earns a line only when they played under another one.
  const aliasOf = useCallback((row: ParticipationRow) => (row.name === personName ? null : row.name), [personName]);

  const columns = useMemo<ColumnDef<ParticipationRow>[]>(
    () => [
      {
        accessorKey: "tournament_name",
        header: t("tournament"),
        size: 220,
        meta: columnMeta<ParticipationRow>({
          sticky: true,
          searchValue: (row) => row.tournament_name
        }),
        cell: ({ row }) => (
          <Link
            className="font-medium underline-offset-4 hover:underline"
            href={`/admin/tournaments/${row.original.tournament_id}/overview`}
          >
            {row.original.tournament_name}
          </Link>
        )
      },
      {
        accessorKey: "team_name",
        header: t("team"),
        enableSorting: false,
        meta: columnMeta<ParticipationRow>({ searchValue: (row) => `${row.team_name} ${row.name}` }),
        cell: ({ row }) => {
          const alias = aliasOf(row.original);
          return (
            <div className="min-w-0">
              <Link className="underline-offset-4 hover:underline" href={`/admin/teams/${row.original.team_id}`}>
                {row.original.team_name}
              </Link>
              {alias ? (
                <p className="truncate text-caption text-muted-foreground" title={alias}>
                  {alias}
                </p>
              ) : null}
            </div>
          );
        }
      },
      {
        accessorKey: "role",
        header: t("role"),
        cell: ({ row }) => {
          const subRole = formatSubRoleLabel(subRoleOf(row.original.role));
          return (
            <div className="flex items-center gap-2">
              <ParticipationRole row={row.original} />
              {subRole ? <span className="truncate text-caption text-muted-foreground">{subRole}</span> : null}
              <ParticipationFlags row={row.original} />
            </div>
          );
        }
      },
      {
        // Division is derived from rank, so the two ride in one column and sort
        // by the finer of the pair; an unranked row sorts last either way.
        id: "rank",
        accessorFn: (row) => row.rank ?? undefined,
        sortUndefined: "last",
        header: t("divRank"),
        cell: ({ row }) => (
          <div className="flex items-center gap-2">
            <DivisionIcon
              division={row.original.division}
              tournamentGrid={row.original.division_grid_version}
              width={28}
              height={28}
            />
            <span className="tabular-nums">{row.original.rank ?? "—"}</span>
          </div>
        )
      },
      createKebabColumn<ParticipationRow>(
        (row) => [
          {
            label: t("edit"),
            icon: Pencil,
            hidden: !canUpdate,
            onSelect: () => openEdit(row)
          },
          {
            label: t("remove"),
            icon: Trash2,
            destructive: true,
            hidden: !canDelete,
            onSelect: () => setPendingDelete(row)
          }
        ],
        // The hub already names the person; the tournament is what tells one row's menu from the next.
        { rowLabel: (row) => row.tournament_name }
      )
    ],
    // `openEdit` was missing here: the kebab's "Edit participation" called
    // whichever closure the first render happened to build. It carries
    // `personId` itself, so the column list no longer needs it separately.
    [t, canUpdate, canDelete, openEdit, aliasOf]
  );

  return (
    // Flush while the table shows: its own toolbar and rows run edge to edge.
    <SettingGroup
      id="participations"
      title={t("title")}
      actions={
        canCreate ? (
          <Button size="sm" onClick={openCreate}>
            <Plus aria-hidden className="size-4" />
            {t("add")}
          </Button>
        ) : null
      }
      flush={!participationsQuery.isError}
    >
      {participationsQuery.isError ? (
        <LoadErrorNote title={t("loadError")} onRetry={() => void participationsQuery.refetch()} />
      ) : (
        <DataTable<ParticipationRow>
          framed={false}
          rows={rows}
          isLoading={participationsQuery.isLoading}
          columns={columns}
          initialPageSize={20}
          getRowId={(row) => String(row.id)}
          searchPlaceholder={t("search")}
          emptyMessage={t("empty")}
          onRowDoubleClick={canUpdate ? (row) => openEdit(row.original) : undefined}
          renderMobileCard={(row) => {
            const alias = aliasOf(row.original);
            const subRole = formatSubRoleLabel(subRoleOf(row.original.role));
            return (
              <div className="min-w-0 flex-1">
                <Link
                  className="block truncate text-body font-medium underline-offset-4 hover:underline"
                  href={`/admin/tournaments/${row.original.tournament_id}/overview`}
                >
                  {row.original.tournament_name}
                </Link>
                <p className="truncate text-caption text-muted-foreground">
                  {row.original.team_name}
                  {alias ? ` · ${alias}` : ""}
                </p>
                <div className="flex items-center gap-2 text-caption text-muted-foreground">
                  <span>
                    <ParticipationRole row={row.original} named />
                    {subRole ? ` · ${subRole}` : ""} · <span className="tabular-nums">{row.original.rank ?? "—"}</span>
                  </span>
                  <ParticipationFlags row={row.original} />
                </div>
              </div>
            );
          }}
        />
      )}

      <EntityFormDialog
        open={formMode != null}
        onOpenChange={(next) => {
          if (!next) closeForm();
        }}
        title={formMode === "edit" ? t("edit") : t("add")}
        description={
          formMode === "edit"
            ? t("editDescription", { tournament: editing?.tournament_name ?? "" })
            : t("addDescription")
        }
        isSubmitting={saveMutation.isPending}
        submittingLabel={formMode === "edit" ? t("updating") : t("adding")}
        errorMessage={saveError ?? (formMode !== null && ownerScopeMissing ? roleT("ownerScopeError") : subRolesQuery.isError ? roleT("roleLoadError") : metadataFailed ? roleT("metadataError") : undefined)}
        isDirty={formMode != null && hasUnsavedChanges(form, formInitial)}
        onSubmit={(event) => {
          event.preventDefault();
          if (ownerScopeMissing || subRolesQuery.isError) {
            setSaveError(roleT(ownerScopeMissing ? "ownerScopeError" : "roleLoadError"));
            return;
          }
          const invalid = playerFormError(form, formMode ?? "edit");
          if (invalid) {
            setSaveError(formT(invalid));
            return;
          }
          // Past this point the owner game is known; its metadata names the dimension the role is written in.
          if (!ratedCode) {
            setSaveError(roleT("metadataError"));
            return;
          }
          saveMutation.mutate({ state: form, dimension: ratedCode });
        }}
      >
        <PlayerForm
          mode={formMode === "edit" ? "edit" : "create"}
          value={form}
          onChange={setForm}
          subRoles={subRolesQuery.data}
          ontology={ontology}
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
          title: t("remove"),
          description: t("removeDescription", { tournament: pendingDelete?.tournament_name ?? t("tournament") }),
          confirmLabel: t("remove"),
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </SettingGroup>
  );
}
