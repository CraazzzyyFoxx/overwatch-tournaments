"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { Pencil, Plus, Trash2, Users } from "lucide-react";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { TeamRosterEditorDialog } from "@/components/admin/teams/TeamRosterEditorDialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { usePermissions } from "@/hooks/usePermissions";
import { notify } from "@/lib/notify";
import { paginateResults, sortArray } from "@/lib/paginate-results";
import adminService from "@/services/admin.service";
import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { Team } from "@/types/team.types";

const TOURNAMENT_QUERY_PARAM = "tournament";

function parseTournamentQueryParam(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export default function TeamsPage() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const queryClient = useQueryClient();

  const canCreateTeam = canAccessPermission("team.create", workspaceId);
  const canUpdateTeam = canAccessPermission("team.update", workspaceId);
  const canDeleteTeam = canAccessPermission("team.delete", workspaceId);
  const canCreatePlayer = canAccessPermission("player.create", workspaceId);
  const canUpdatePlayer = canAccessPermission("player.update", workspaceId);
  const canDeletePlayer = canAccessPermission("player.delete", workspaceId);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null);

  const selectedTournamentId = parseTournamentQueryParam(searchParams.get(TOURNAMENT_QUERY_PARAM));

  const { data: tournamentsData } = useQuery({
    queryKey: ["tournaments"],
    queryFn: () => tournamentService.getAll(null)
  });

  const selectedTournament =
    tournamentsData?.results.find((tournament) => tournament.id === selectedTournamentId) ?? null;

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteTeam(id),
    onSuccess: () => {
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ["teams"] }),
        queryClient.invalidateQueries({ queryKey: ["tournaments"] }),
        selectedTeam?.tournament_id != null
          ? queryClient.invalidateQueries({
              queryKey: ["admin", "tournament", selectedTeam.tournament_id, "teams"]
            })
          : Promise.resolve()
      ]);
      setDeleteDialogOpen(false);
      setSelectedTeam(null);
      notify.success("Team deleted successfully");
    }
  });

  const handleDelete = (team: Team) => {
    setSelectedTeam(team);
    setDeleteDialogOpen(true);
  };

  const handleConfirmDelete = () => {
    if (selectedTeam) {
      deleteMutation.mutate(selectedTeam.id);
    }
  };

  const handleTournamentFilterChange = (value: string) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (value === "all") {
      nextParams.delete(TOURNAMENT_QUERY_PARAM);
    } else {
      nextParams.set(TOURNAMENT_QUERY_PARAM, value);
    }

    const query = nextParams.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const canOpenCreateDialog = canCreateTeam && canCreatePlayer && selectedTournamentId != null;
  const canOpenEditDialog = canUpdateTeam || canCreatePlayer || canUpdatePlayer || canDeletePlayer;

  const columns: ColumnDef<Team>[] = [
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <div className="font-medium">{row.getValue("name")}</div>
    },
    {
      accessorKey: "avg_sr",
      header: "Avg SR",
      cell: ({ row }) => <div>{row.getValue<number>("avg_sr").toFixed(0)}</div>
    },
    {
      accessorKey: "total_sr",
      header: "Total SR",
      cell: ({ row }) => <div>{row.getValue("total_sr")}</div>
    },
    {
      accessorKey: "players",
      header: "Players",
      enableSorting: false,
      cell: ({ row }) => (
        <div className="flex items-center gap-1">
          <Users className="h-4 w-4" />
          {row.getValue<any[]>("players")?.length || 0}
        </div>
      )
    },
    {
      accessorKey: "tournament",
      header: "Tournament",
      enableSorting: false,
      cell: ({ row }) => {
        const tournament = row.getValue<any>("tournament");
        return tournament ? (
          <div className="text-sm text-muted-foreground">{tournament.name}</div>
        ) : (
          "—"
        );
      }
    },
    {
      id: "actions",
      cell: ({ row }) =>
        canOpenEditDialog || canDeleteTeam ? (
          <div className="flex items-center gap-2">
            {canOpenEditDialog ? (
              <Button
                aria-label={`Edit ${row.original.name}`}
                variant="ghost"
                size="icon"
                onClick={() => {
                  setSelectedTeam(row.original);
                  setEditDialogOpen(true);
                }}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            ) : null}
            {canDeleteTeam ? (
              <Button
                aria-label={`Delete ${row.original.name}`}
                variant="ghost"
                size="icon"
                onClick={() => handleDelete(row.original)}
                className="text-destructive"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            ) : null}
          </div>
        ) : null
    }
  ];

  return (
    <div className="flex flex-col gap-6">
      <AdminPageHeader
        title="Teams"
        description="Manage teams and their rosters"
        actions={
          canOpenCreateDialog ? (
            <Button onClick={() => setCreateDialogOpen(true)}>
              <Plus className="mr-2 h-4 w-4" />
              Create Team
            </Button>
          ) : null
        }
      />

      <div className="flex flex-wrap items-center gap-4">
        <Label htmlFor="tournament-filter">Filter by Tournament:</Label>
        <Select
          value={selectedTournamentId?.toString() || "all"}
          onValueChange={handleTournamentFilterChange}
        >
          <SelectTrigger className="w-[300px]">
            <SelectValue placeholder="All Tournaments" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Tournaments</SelectItem>
            {tournamentsData?.results.map((tournament) => (
              <SelectItem key={tournament.id} value={tournament.id.toString()}>
                {tournament.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {canCreateTeam && !selectedTournamentId ? (
          <span className="text-sm text-muted-foreground">
            Select a tournament to create a team roster.
          </span>
        ) : null}
      </div>

      <AdminDataTable
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
          const data = await teamService.getAll({ tournamentId: selectedTournamentId });
          const filteredTeams = search
            ? data.results.filter((team) => team.name.toLowerCase().includes(search.toLowerCase()))
            : data.results;
          const sorted = sortArray(filteredTeams, sortField, sortDir);

          return paginateResults(sorted, page, pageSize);
        }}
        columns={columns}
        searchPlaceholder="Search teams..."
        emptyMessage="No teams found."
        onRowClick={(row) => router.push(`/admin/teams/${row.original.id}`)}
      />

      {selectedTournamentId != null ? (
        <TeamRosterEditorDialog
          key={`team-create-${selectedTournamentId}-${createDialogOpen ? "open" : "closed"}`}
          open={createDialogOpen}
          onOpenChange={setCreateDialogOpen}
          mode="create"
          tournamentId={selectedTournamentId}
          workspaceId={selectedTournament?.workspace_id ?? workspaceId}
          canCreateTeam={canCreateTeam}
          canUpdateTeam={canUpdateTeam}
          canCreatePlayer={canCreatePlayer}
          canUpdatePlayer={canUpdatePlayer}
          canDeletePlayer={canDeletePlayer}
        />
      ) : null}

      {selectedTeam ? (
        <TeamRosterEditorDialog
          key={`team-edit-${selectedTeam.id}-${editDialogOpen ? "open" : "closed"}`}
          open={editDialogOpen}
          onOpenChange={(open) => {
            setEditDialogOpen(open);
            if (!open) {
              setSelectedTeam(null);
            }
          }}
          mode="edit"
          tournamentId={selectedTeam.tournament_id}
          workspaceId={selectedTeam.tournament?.workspace_id ?? workspaceId}
          team={selectedTeam}
          canCreateTeam={canCreateTeam}
          canUpdateTeam={canUpdateTeam}
          canCreatePlayer={canCreatePlayer}
          canUpdatePlayer={canUpdatePlayer}
          canDeletePlayer={canDeletePlayer}
        />
      ) : null}

      {canDeleteTeam ? (
        <DeleteConfirmDialog
          open={deleteDialogOpen}
          onOpenChange={setDeleteDialogOpen}
          onConfirm={handleConfirmDelete}
          title="Delete Team"
          description={`Are you sure you want to delete "${selectedTeam?.name}"? This action cannot be undone.`}
          cascadeInfo={["All players in this team", "All related match statistics"]}
          isDeleting={deleteMutation.isPending}
        />
      ) : null}
    </div>
  );
}
