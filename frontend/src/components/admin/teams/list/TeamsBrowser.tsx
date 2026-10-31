"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { DataTable, type TableCommand } from "@/components/data-table";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import { TeamCreateDialog } from "@/components/admin/teams/TeamCreateDialog";
import { gameFilterDefs } from "@/components/admin/game-filter";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam,
  strandedTournamentParams,
  tournamentOptions
} from "@/components/admin/tournament-filter";
import { RowGameLabel, gameColumn } from "@/components/workspace/game-column";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import type { Team } from "@/types/team.types";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

import { teamFilterDefs } from "./filters";
import { TeamInspectorPanel } from "./TeamInspectorPanel";
import { useTeamColumns } from "./useTeamColumns";

const PAGE_SIZE = 15;

/**
 * Every roster in the workspace (T2).
 *
 * The tournament scope is a filter-bar chip on the same `?tournament=` param
 * the sibling browsers use, so a pinned link still opens pinned. A row opens
 * the inspector at `?id=` — the roster summary — and "Open page" goes on to
 * the team editor, which is where a roster is actually changed.
 *
 * A multi list (spec §6.9): the "Game" chip on `?discipline=` comes first; `discipline: null` is every game's teams
 * with a "Game" column, a code is that game's teams, filtered on the server through the team's tournament.
 */
export function TeamsBrowser({
  workspaceId,
  discipline,
  games
}: Readonly<{
  workspaceId: number;
  discipline: string | null;
  /** The community's games, for the Game chip. */
  games: readonly DisciplineDescriptor[] | undefined;
}>) {
  const t = useTranslations("adminPeople.teams");
  const tGame = useTranslations("common.discipline");
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const router = useRouter();
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row sits on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;

  const canCreateTeam = canAccessPermission("team.create", workspaceId);
  const canDeleteTeam = canAccessPermission("team.delete", workspaceId);

  const [pageRows, setPageRows] = useState<Team[]>([]);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Team | null>(null);

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.adminList(workspaceId, ALL_DISCIPLINES),
    queryFn: () => tournamentService.getAll(null, workspaceId)
  });

  const selectedTournamentId = parseTournamentQueryParam(searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null);
  const selectedTournamentGame = tournamentsQuery.data?.results.find(
    (tournament) => tournament.id === selectedTournamentId
  )?.discipline;

  // The tournament chip offers the filtered game's tournaments, or every game's under "all games"; a game pick drops
  // a tournament of another game.
  const defs = useMemo(
    () => [
      ...gameFilterDefs(games, tGame("column"), (next) => strandedTournamentParams(selectedTournamentGame, next)),
      ...teamFilterDefs(tournamentOptions(tournamentsQuery.data?.results ?? [], discipline), t("labels.tournament"))
    ],
    [games, selectedTournamentGame, discipline, t, tGame, tournamentsQuery.data]
  );

  const filters = useFilters(defs);

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteTeam(id),
    onSuccess: () => {
      const removed = pendingDelete;
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.teamsAll() }),
        queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.list() }),
        removed?.tournament_id != null
          ? queryClient.invalidateQueries({
              queryKey: adminQueryKeys.tournamentTeams(removed.tournament_id)
            })
          : Promise.resolve()
      ]);
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success(t("deleted"));
    }
  });

  const baseColumns = useTeamColumns({ canDelete: canDeleteTeam, onDelete: setPendingDelete });
  const columns =
    discipline === null
      ? [baseColumns[0], gameColumn<Team>(tGame("column"), (team) => team.tournament?.discipline), ...baseColumns.slice(1)]
      : baseColumns;

  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  // A team belongs to one tournament: until the list is scoped to one, the
  // command is there but says what it is waiting for.
  const commands: TableCommand[] = [
    {
      id: "create",
      label: t("create"),
      icon: Plus,
      primary: true,
      hidden: !canCreateTeam,
      disabledReason: selectedTournamentId == null ? t("pickTournament") : undefined,
      onSelect: () => setCreateDialogOpen(true)
    }
  ];

  return (
    <>
      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <DataTable<Team>
            columns={columns}
            initialPageSize={PAGE_SIZE}
            searchPlaceholder={t("search")}
            filterKey={filters.filterKey}
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            toolbar={<FilterBar defs={defs} filters={filters} />}
            commands={commands}
            emptyMessage={
              selectedTournamentId
                ? t("emptyFiltered")
                : t("empty")
            }
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            onRowDoubleClick={(row) => router.push(`/admin/teams/${row.original.id}`)}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{row.original.name}</p>
                {discipline === null && row.original.tournament?.discipline ? (
                  <RowGameLabel
                    code={row.original.tournament.discipline}
                    className="flex text-xs text-muted-foreground"
                  />
                ) : null}
                <p className="truncate text-xs text-muted-foreground">
                  {row.original.tournament?.name ?? t("noTournamentShort")}
                </p>
                <p className="text-xs text-muted-foreground">
                  {t.rich("mobileSummary", {
                    count: row.original.players?.length ?? 0,
                    avgSr: row.original.avg_sr.toFixed(0),
                    num: (chunks) => <span className="tabular-nums">{chunks}</span>
                  })}
                </p>
              </div>
            )}
            queryKey={(page, search, pageSize, sortField, sortDir) => [
              "teams",
              workspaceId,
              selectedTournamentId,
              page,
              search,
              pageSize,
              sortField,
              sortDir,
              discipline
            ]}
            queryFn={(page, search, pageSize, sortField, sortDir) =>
              teamService.getAll({
                workspaceId,
                tournamentId: selectedTournamentId,
                page,
                perPage: pageSize,
                search: search || undefined,
                sort: sortField ?? "avg_sr",
                order: sortField ? sortDir : "asc",
                discipline
              })
            }
            onPageRowsChange={setPageRows}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow?.name ?? ""}
          openHref={openRow ? `/admin/teams/${openRow.id}` : undefined}
          onPrev={
            openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
          }
          onNext={
            openIndex >= 0 && openIndex < pageRows.length - 1
              ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
              : undefined
          }
        >
          {openRow ? <TeamInspectorPanel team={openRow} /> : null}
        </Inspector>
      </div>

      {selectedTournamentId != null ? (
        <TeamCreateDialog
          open={createDialogOpen}
          onOpenChange={setCreateDialogOpen}
          tournamentId={selectedTournamentId}
        />
      ) : null}

      <ConfirmDialog
        open={pendingDelete != null}
        onOpenChange={(next) => {
          if (!next) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: t("delete"),
          description: t("deleteDescription", { name: pendingDelete?.name ?? t("teamName") }),
          confirmLabel: t("delete"),
          tone: "danger",
          cascade: [t("cascadePlayers"), t("cascadeStats")]
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </>
  );
}
