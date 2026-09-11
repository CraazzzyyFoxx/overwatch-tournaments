"use client";

import { useId, useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2, Users } from "lucide-react";

import TeamName from "@/components/TeamName";
import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { AdminFilterBar } from "@/components/admin/kit/AdminFilterBar";
import { AdminInspector } from "@/components/admin/kit/AdminInspector";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";
import { createKebabColumn } from "@/components/admin/kit/kebab-column";
import { useAdminFilters, type FilterDef } from "@/components/admin/kit/useAdminFilters";
import { TeamCreateDialog } from "@/components/admin/teams/TeamCreateDialog";
import { EYEBROW_CLASS } from "@/components/admin/tone";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam
} from "@/components/admin/tournament-filter";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Player, Team } from "@/types/team.types";

const PAGE_SIZE = 15;

function InspectorField({
  label,
  children
}: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <p className="mt-0.5 truncate text-sm text-foreground">{children}</p>
    </div>
  );
}

function RosterList({ players }: Readonly<{ players: Player[] }>) {
  if (players.length === 0) {
    return <p className="mt-2 text-xs text-muted-foreground">Nobody here yet.</p>;
  }

  return (
    <ul className="mt-2 space-y-1 text-sm">
      {players.map((player) => (
        <li key={player.id} className="flex items-center justify-between gap-2">
          <span className="truncate">{player.user?.name ?? player.name}</span>
          <span className="shrink-0 text-xs text-muted-foreground">
            {player.role}
            {" · "}
            <span className="font-mono tabular-nums">{player.rank}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/** What the inspector shows for a roster, before opening the editor page. */
function RosterSummary({ team }: Readonly<{ team: Team }>) {
  const players = team.players ?? [];
  const starters = players.filter((player) => !player.is_substitution);
  const substitutes = players.filter((player) => player.is_substitution);
  // The captain is a roster row, so their name comes from the linked identity;
  // a captain inherited from before that rule can sit off the roster.
  const captain = players.find((player) => player.user_id === team.captain_id);

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        <InspectorField label="Captain">
          {captain?.user?.name ??
            captain?.name ??
            (team.captain_id > 0 ? `User #${team.captain_id}` : "—")}
        </InspectorField>
        <InspectorField label="Roster">
          <span className="font-mono tabular-nums">{starters.length}</span> starters
          {substitutes.length > 0 ? ` + ${substitutes.length} subs` : ""}
        </InspectorField>
        <InspectorField label="Average SR">
          <span className="font-mono tabular-nums">{team.avg_sr.toFixed(0)}</span>
        </InspectorField>
        <InspectorField label="Total SR">
          <span className="font-mono tabular-nums">{team.total_sr}</span>
        </InspectorField>
        <InspectorField label="Group">{team.group?.name ?? "—"}</InspectorField>
        <InspectorField label="Placement">
          {team.placement != null ? (
            <span className="font-mono tabular-nums">#{team.placement}</span>
          ) : (
            "—"
          )}
        </InspectorField>
      </div>

      <section className="rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Starters</p>
        <RosterList players={starters} />
      </section>

      <section className="rounded-xl border border-border/60 p-3">
        <p className={EYEBROW_CLASS}>Substitutes</p>
        <RosterList players={substitutes} />
      </section>
    </div>
  );
}

/**
 * Every roster in the workspace (T2).
 *
 * The tournament scope is a filter-bar chip on the same `?tournament=` param
 * the sibling browsers use, so a pinned link still opens pinned. A row opens
 * the inspector at `?id=` — the roster summary — and "Open page" goes on to
 * the team editor, which is where a roster is actually changed.
 */
export default function TeamsPage() {
  const { canAccessPermission, isLoaded } = usePermissions();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const queryClient = useQueryClient();
  // `id` is the inspector, not a filter: opening a row must not drop the page
  // the row sits on, so nothing resets here.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const canReadTeam = canAccessPermission("team.read", workspaceId);
  const canCreateTeam = canAccessPermission("team.create", workspaceId);
  const canDeleteTeam = canAccessPermission("team.delete", workspaceId);

  const [pageRows, setPageRows] = useState<Team[]>([]);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Team | null>(null);
  const createHintId = useId();

  const tournamentsQuery = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null)
  });

  const defs = useMemo<FilterDef[]>(
    () => [
      {
        // The URL keeps the `tournament` spelling the sibling admin browsers
        // already use, so a link that pins a tournament still opens pinned.
        key: TOURNAMENT_QUERY_PARAM,
        label: "Tournament",
        kind: "single",
        options: (tournamentsQuery.data?.results ?? []).map((tournament) => ({
          value: String(tournament.id),
          label: tournament.name
        }))
      }
    ],
    [tournamentsQuery.data]
  );

  const filters = useAdminFilters(defs);
  const selectedTournamentId = parseTournamentQueryParam(
    String(filters.values[TOURNAMENT_QUERY_PARAM] ?? "") || null
  );

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteTeam(id),
    onSuccess: () => {
      const removed = pendingDelete;
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["teams"] }),
        queryClient.invalidateQueries({ queryKey: ["tournaments"] }),
        removed?.tournament_id != null
          ? queryClient.invalidateQueries({
              queryKey: ["admin", "tournament", removed.tournament_id, "teams"]
            })
          : Promise.resolve()
      ]);
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success("Team deleted successfully");
    }
  });

  const createBlockedReason =
    canCreateTeam && selectedTournamentId == null
      ? "Pick a tournament first — a roster belongs to one tournament."
      : null;

  const columns = useMemo<ColumnDef<Team>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        cell: ({ row }) => <TeamName team={row.original} size="xs" nameClassName="font-medium" />
      },
      {
        accessorKey: "avg_sr",
        header: "Avg SR",
        cell: ({ row }) => (
          <div className="font-mono tabular-nums">{row.original.avg_sr.toFixed(0)}</div>
        )
      },
      {
        accessorKey: "total_sr",
        header: "Total SR",
        cell: ({ row }) => <div className="font-mono tabular-nums">{row.original.total_sr}</div>
      },
      {
        accessorKey: "players",
        header: "Players",
        enableSorting: false,
        cell: ({ row }) => (
          <div className="flex items-center gap-1 tabular-nums">
            <Users className="h-4 w-4" aria-hidden />
            {row.original.players?.length ?? 0}
          </div>
        )
      },
      {
        accessorKey: "tournament",
        header: "Tournament",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.tournament ? (
            <div className="text-sm text-muted-foreground">{row.original.tournament.name}</div>
          ) : (
            "—"
          )
      },
      createKebabColumn<Team>(
        (row) => [
          { label: "Open page", href: `/admin/teams/${row.id}` },
          {
            label: "Delete team",
            icon: Trash2,
            destructive: true,
            hidden: !canDeleteTeam,
            onSelect: () => setPendingDelete(row)
          }
        ],
        { rowLabel: (row) => row.name }
      )
    ],
    [canDeleteTeam]
  );

  if (!isLoaded) return <Skeleton className="h-64 w-full rounded-xl" />;

  if (!canReadTeam) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Unauthorized</CardTitle>
          <CardDescription>
            You do not have permission to read teams in this workspace.
          </CardDescription>
        </CardHeader>
      </Card>
    );
  }

  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Teams"
        description="Open a team to edit its name, captain and roster."
      />

      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <AdminDataTable<Team>
            columns={columns}
            initialPageSize={PAGE_SIZE}
            searchPlaceholder="Search teams…"
            filterKey={filters.filterKey}
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            toolbar={
              <AdminFilterBar
                defs={defs}
                filters={filters}
                trailing={
                  canCreateTeam ? (
                    <>
                      {createBlockedReason ? (
                        <span id={createHintId} className="text-sm text-muted-foreground">
                          {createBlockedReason}
                        </span>
                      ) : null}
                      <Button
                        size="sm"
                        onClick={() => setCreateDialogOpen(true)}
                        disabled={createBlockedReason != null}
                        aria-describedby={createBlockedReason ? createHintId : undefined}
                      >
                        <Plus className="size-4" aria-hidden />
                        Create team
                      </Button>
                    </>
                  ) : null
                }
              />
            }
            emptyMessage={
              selectedTournamentId
                ? "No teams in this tournament yet. Use “Create team” to add the first roster."
                : "No teams yet. Pick a tournament to see or create its rosters."
            }
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{row.original.name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {row.original.tournament?.name ?? "No tournament"}
                </p>
                <p className="text-xs text-muted-foreground">
                  <span className="font-mono tabular-nums">
                    {row.original.players?.length ?? 0}
                  </span>{" "}
                  players · avg SR{" "}
                  <span className="font-mono tabular-nums">{row.original.avg_sr.toFixed(0)}</span>
                </p>
              </div>
            )}
            queryKey={(page, search, pageSize, sortField, sortDir) => [
              "teams",
              selectedTournamentId,
              page,
              search,
              pageSize,
              sortField,
              sortDir
            ]}
            queryFn={async (page, search, pageSize, sortField, sortDir) => {
              const result = await teamService.getAll({
                tournamentId: selectedTournamentId,
                page,
                perPage: pageSize,
                search: search || undefined,
                sort: sortField ?? "avg_sr",
                order: sortField ? sortDir : "asc"
              });
              setPageRows(result.results);
              return result;
            }}
          />
        </div>

        <AdminInspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow?.name ?? ""}
          subtitle={openRow?.tournament?.name ?? undefined}
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
          {openRow ? <RosterSummary team={openRow} /> : null}
        </AdminInspector>
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
          title: "Delete team",
          description: `Deleting “${pendingDelete?.name ?? "this team"}” removes the roster from its tournament along with every player and match statistic below. This cannot be undone.`,
          confirmLabel: "Delete team",
          tone: "danger",
          cascade: ["All players in this team", "All related match statistics"]
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
