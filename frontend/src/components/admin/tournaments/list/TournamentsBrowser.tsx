"use client";

import { useCallback, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { DataTable, type TableCommand } from "@/components/data-table";
import { gameFilterDefs } from "@/components/admin/game-filter";
import { CreateTournamentDialog } from "@/components/admin/tournaments/CreateTournamentDialog";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { PageStateCard } from "@/components/ui/page-state-card";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { useGameScope } from "@/hooks/useGameScope";
import { useQueryParams } from "@/hooks/useQueryParams";
import { ALL_DISCIPLINES, defaultCreationGame, showsGameMarks } from "@/lib/site/discipline-scope";
import { notify } from "@/lib/notify";
import tournamentService from "@/services/tournament.service";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";
import { usePermissions } from "@/hooks/usePermissions";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

import { TournamentMobileCard, useTournamentColumns } from "./useTournamentColumns";

/** The lifecycle chip: which rows each option keeps. */
const LIFECYCLE = {
  live: (tournament: Tournament) => tournament.status === "live" || tournament.status === "playoffs",
  registration: (tournament: Tournament) =>
    tournament.status === "registration" || tournament.status === "check_in",
  unpublished: (tournament: Tournament) => tournament.is_hidden,
  finished: (tournament: Tournament) =>
    tournament.is_finished || tournament.status === "completed" || tournament.status === "archived"
} as const;
type Lifecycle = keyof typeof LIFECYCLE;
const LIFECYCLE_KEYS = Object.keys(LIFECYCLE) as Lifecycle[];

function isLifecycle(value: string): value is Lifecycle {
  return value in LIFECYCLE;
}

/**
 * Every tournament in the workspace (T2). A row opens the hub; there is no
 * Inspector because the hub is one click away and says everything a panel
 * would. `?create=1` is the "Create tournament" dialog: the table's Create
 * command sets it, and the dashboard and other pages open it with a link.
 */
export function TournamentsBrowser() {
  const t = useTranslations("adminTournaments.list");
  const tGame = useTranslations("common.discipline");
  const router = useRouter();
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const canCreate = canAccessPermission("tournament.create", currentWorkspaceId);
  const canDelete = canAccessPermission("tournament.delete", currentWorkspaceId);
  // Shallow: opening adds no history entry, and the param is gone before a new tournament's page is pushed, so Back
  // from it lands on the plain list rather than a reopened dialog.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const closeCreate = () => setParams({ create: null });

  const [pendingDelete, setPendingDelete] = useState<Tournament | null>(null);

  // Every game's tournaments with no game filtered, one game's under the game chip (`?discipline=`); the server
  // filters. The list is the workspace's: a first visit learns its community after mounting, and nothing is read until then.
  const gameScope = useGameScope({ axis: currentWorkspaceId ?? "all" });
  const discipline = gameScope.game;
  const gameKind = gameScope.resolution?.game.kind;
  const ready = currentWorkspaceId !== null && (gameKind === "all" || gameKind === "game");
  const descriptors = useGameDescriptors();
  const games =
    gameScope.resolution !== null && showsGameMarks(gameScope.resolution, gameScope.games ?? [])
      ? descriptors
      : undefined;
  // A new tournament starts in the filtered game, else the area's first enabled one (spec §7.2).
  const creationGames = (gameScope.games ?? []).filter((game) => game.enabled);
  const creationGame = defaultCreationGame(discipline, creationGames);

  const tournamentsQuery = useQuery({
    // Its own entry: the pickers sharing `adminList` load no stages, and this table draws them.
    queryKey: [...tournamentQueryKeys.adminList(currentWorkspaceId, discipline ?? ALL_DISCIPLINES), "stages"],
    queryFn: () => tournamentService.getAll(null, currentWorkspaceId, discipline, ["stages", "participants_count"]),
    enabled: ready
  });
  const tournaments = useMemo(() => tournamentsQuery.data?.results ?? [], [tournamentsQuery.data]);

  const defs = useMemo<FilterDef[]>(
    () => [
      ...gameFilterDefs(gameScope.games, tGame("column")),
      {
        key: "status",
        label: t("columns.status"),
        kind: "single",
        options: LIFECYCLE_KEYS.map((key) => ({
          value: key,
          label: t(`status.${key}`),
          count: tournaments.filter(LIFECYCLE[key]).length
        }))
      }
    ],
    [t, tGame, gameScope.games, tournaments]
  );
  const filters = useFilters(defs);
  const lifecycle = String(filters.values.status ?? "");
  const rows = isLifecycle(lifecycle) ? tournaments.filter(LIFECYCLE[lifecycle]) : tournaments;

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteTournament(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.list() });
      setPendingDelete(null);
      notify.success(t("deleted"));
    }
  });

  const columns = useTournamentColumns({
    canDelete,
    onDelete: useCallback((tournament: Tournament) => setPendingDelete(tournament), []),
    games
  });

  const commands: TableCommand[] = [
    {
      id: "create",
      label: t("create"),
      icon: Plus,
      onSelect: () => setParams({ create: 1 }),
      primary: true,
      hidden: !canCreate
    }
  ];

  if (gameKind === "invalid" || gameKind === "empty") {
    return <GameScopeControl scope={gameScope} variant="multi" />;
  }
  if (tournamentsQuery.isError || gameScope.isError) {
    return (
      <PageStateCard
        state="error"
        onAction={() => {
          if (gameScope.isError) gameScope.refetch();
          void tournamentsQuery.refetch();
        }}
      />
    );
  }

  return (
    <>
      <DataTable<Tournament>
        rows={rows}
        isLoading={!ready || tournamentsQuery.isLoading}
        columns={columns}
        getRowId={(tournament) => String(tournament.id)}
        searchPlaceholder={t("searchPlaceholder")}
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={defs} filters={filters} />}
        commands={commands}
        emptyMessage={t("empty")}
        onRowClick={(row) => router.push(`/admin/tournaments/${row.original.id}`)}
        renderMobileCard={(row) => <TournamentMobileCard tournament={row.original} games={games} />}
      />

      {canDelete ? (
        <ConfirmDialog
          open={pendingDelete !== null}
          onOpenChange={(open) => {
            if (!open) setPendingDelete(null);
          }}
          onConfirm={() => {
            if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
          }}
          pending={deleteMutation.isPending}
          intent={{
            title: t("deleteTitle"),
            description: t("deleteDescription", { name: pendingDelete?.name ?? "" }),
            confirmLabel: t("delete"),
            tone: "danger",
            cascade: [
              t("cascade.stages"),
              t("cascade.teams"),
              t("cascade.players"),
              t("cascade.encounters"),
              t("cascade.standings")
            ]
          }}
        />
      ) : null}

      {canCreate && currentWorkspaceId !== null && creationGame !== null && searchParams?.get("create") === "1" ? (
        <CreateTournamentDialog
          workspaceId={currentWorkspaceId}
          games={creationGames}
          defaultGame={creationGame}
          onClose={closeCreate}
          onCreated={(tournament) => {
            closeCreate();
            router.push(`/admin/tournaments/${tournament.id}/overview`);
          }}
        />
      ) : null}
    </>
  );
}
