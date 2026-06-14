"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ColumnDef } from "@tanstack/react-table";
import { Plus, Pencil, Trash2, CheckCircle, XCircle, Crown, Trophy } from "lucide-react";
import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import {
  TournamentFormFields,
  type TournamentFormFieldsValue
} from "@/components/admin/tournaments/TournamentFormFields";
import { Button } from "@/components/ui/button";
import { notify } from "@/lib/notify";
import tournamentService from "@/services/tournament.service";
import adminService from "@/services/admin.service";
import workspaceService from "@/services/workspace.service";
import { Tournament } from "@/types/tournament.types";
import { TournamentCreateInput, TournamentUpdateInput } from "@/types/admin.types";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { usePermissions } from "@/hooks/usePermissions";
import { normalizeChallongeSlug } from "@/lib/challonge";
import { hasUnsavedChanges } from "@/lib/form-change";
import { paginateResults, sortArray } from "@/lib/paginate-results";
import { formatTournamentStages } from "@/lib/tournament-stages";
import { useWorkspaceStore } from "@/stores/workspace.store";

type TournamentFormData = TournamentFormFieldsValue & {
  name: string;
  description: string;
  is_league: boolean;
  number: number | null;
  start_date: string;
  end_date: string;
};

const emptyTournamentForm: TournamentFormData = {
  name: "",
  description: "",
  is_league: false,
  number: null,
  division_grid_version_id: null,
  start_date: "",
  end_date: ""
};

function getTournamentEditForm(tournament: Tournament): TournamentFormData {
  return {
    number: tournament.number ?? null,
    name: tournament.name,
    description: tournament.description || "",
    challonge_slug: tournament.challonge_slug || "",
    is_league: tournament.is_league,
    is_finished: tournament.is_finished,
    division_grid_version_id: tournament.division_grid_version_id ?? null,
    start_date: new Date(tournament.start_date).toISOString().split("T")[0],
    end_date: new Date(tournament.end_date).toISOString().split("T")[0]
  };
}

function getCreatePayload(
  formData: TournamentFormData,
  workspaceId: number
): TournamentCreateInput {
  return {
    workspace_id: workspaceId,
    name: formData.name,
    description: formData.description,
    is_league: formData.is_league,
    start_date: formData.start_date,
    end_date: formData.end_date,
    division_grid_version_id: formData.division_grid_version_id,
    ...(formData.number === null ? {} : { number: formData.number })
  };
}

function getUpdatePayload(formData: TournamentFormData): TournamentUpdateInput {
  return {
    number: formData.number,
    name: formData.name,
    description: formData.description,
    challonge_slug: formData.challonge_slug
      ? normalizeChallongeSlug(formData.challonge_slug)
      : null,
    is_league: formData.is_league,
    is_finished: formData.is_finished,
    start_date: formData.start_date,
    end_date: formData.end_date
  };
}

export default function TournamentsPage() {
  const router = useRouter();
  const { canAccessPermission } = usePermissions();
  const queryClient = useQueryClient();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const canCreate = canAccessPermission("tournament.create", currentWorkspaceId);
  const canUpdate = canAccessPermission("tournament.update", currentWorkspaceId);
  const canDelete = canAccessPermission("tournament.delete", currentWorkspaceId);

  const divisionGridsQuery = useQuery({
    queryKey: ["admin", "tournaments", "create", "division-grids", currentWorkspaceId],
    queryFn: async () => {
      if (!currentWorkspaceId) return [];
      return workspaceService.getDivisionGrids(currentWorkspaceId);
    },
    enabled: Boolean(currentWorkspaceId)
  });

  const divisionGridVersions: DivisionGridVersion[] = (divisionGridsQuery.data ?? [])
    .flatMap((grid) => grid.versions)
    .slice()
    .sort((left, right) => right.version - left.version);

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editDialogOpen, setEditDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [selectedTournament, setSelectedTournament] = useState<Tournament | null>(null);
  const [createMode, setCreateMode] = useState<"manual" | "challonge">("manual");

  // Form state
  const [formData, setFormData] = useState<TournamentFormData>({
    ...emptyTournamentForm
  });
  const [challongeSlug, setChallongeSlug] = useState("");

  // Mutations
  const createMutation = useMutation({
    mutationFn: (data: TournamentCreateInput) => adminService.createTournament(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tournaments"] });
      setCreateDialogOpen(false);
      resetForm();
      notify.success("Tournament created successfully");
    }
  });

  const createWithGroupsMutation = useMutation({
    mutationFn: (params: {
      workspace_id: number;
      number: number;
      challonge_slug: string;
      is_league: boolean;
      start_date: string;
      end_date: string;
      division_grid_version_id?: number | null;
    }) => adminService.createTournamentWithGroups(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tournaments"] });
      setCreateDialogOpen(false);
      resetForm();
      notify.success("Tournament created with stages from Challonge");
    }
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: TournamentUpdateInput }) =>
      adminService.updateTournament(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tournaments"] });
      setEditDialogOpen(false);
      setSelectedTournament(null);
      resetForm();
      notify.success("Tournament updated successfully");
    }
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteTournament(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["tournaments"] });
      setDeleteDialogOpen(false);
      setSelectedTournament(null);
      notify.success("Tournament deleted successfully");
    }
  });

  const resetForm = () => {
    setFormData({ ...emptyTournamentForm });
    setChallongeSlug("");
    setCreateMode("manual");
  };

  const handleCreate = () => {
    createMutation.reset();
    createWithGroupsMutation.reset();
    setCreateDialogOpen(true);
    resetForm();
  };

  const handleEdit = (tournament: Tournament) => {
    updateMutation.reset();
    setSelectedTournament(tournament);
    setFormData(getTournamentEditForm(tournament));
    setEditDialogOpen(true);
  };

  const handleDelete = (tournament: Tournament) => {
    setSelectedTournament(tournament);
    setDeleteDialogOpen(true);
  };

  const handleSubmitCreate = (e: React.FormEvent) => {
    e.preventDefault();
    if (createMode === "challonge") {
      if (!formData.number || !challongeSlug.trim() || !formData.start_date || !formData.end_date)
        return;
      if (!currentWorkspaceId) return;
      createWithGroupsMutation.mutate({
        workspace_id: currentWorkspaceId,
        number: formData.number,
        challonge_slug: normalizeChallongeSlug(challongeSlug),
        is_league: formData.is_league,
        start_date: formData.start_date,
        end_date: formData.end_date,
        division_grid_version_id: formData.division_grid_version_id
      });
    } else {
      if (!currentWorkspaceId) return;
      createMutation.mutate(getCreatePayload(formData, currentWorkspaceId));
    }
  };

  const handleSubmitUpdate = (e: React.FormEvent) => {
    e.preventDefault();
    if (selectedTournament) {
      updateMutation.mutate({
        id: selectedTournament.id,
        data: getUpdatePayload(formData)
      });
    }
  };

  const handleConfirmDelete = () => {
    if (selectedTournament) {
      deleteMutation.mutate(selectedTournament.id);
    }
  };

  const editFormInitial = selectedTournament
    ? getTournamentEditForm(selectedTournament)
    : emptyTournamentForm;
  const isCreateDirty =
    createDialogOpen && (hasUnsavedChanges(formData, emptyTournamentForm) || challongeSlug !== "");
  const isEditDirty = editDialogOpen && hasUnsavedChanges(formData, editFormInitial);

  const activeCreateMutation =
    createMode === "challonge" ? createWithGroupsMutation : createMutation;
  const isCreateSubmitting = activeCreateMutation.isPending;
  const createErrorMessage = activeCreateMutation.isError
    ? activeCreateMutation.error.message
    : undefined;

  const columns: ColumnDef<Tournament>[] = [
    {
      accessorKey: "number",
      header: "#",
      cell: ({ row }) => <div className="font-medium">{row.getValue("number") || "—"}</div>
    },
    {
      accessorKey: "name",
      header: "Name",
      cell: ({ row }) => <div className="font-medium">{row.getValue("name")}</div>
    },
    {
      accessorKey: "is_league",
      header: "Type",
      cell: ({ row }) =>
        row.getValue("is_league") ? (
          <StatusIcon icon={Crown} label="League" variant="info" />
        ) : (
          <StatusIcon icon={Trophy} label="Tournament" variant="muted" />
        )
    },
    {
      accessorKey: "is_finished",
      header: "Status",
      cell: ({ row }) =>
        row.getValue("is_finished") ? (
          <StatusIcon icon={CheckCircle} label="Finished" variant="muted" />
        ) : (
          <StatusIcon icon={XCircle} label="Active" variant="success" />
        )
    },
    {
      accessorKey: "start_date",
      header: "Start Date",
      cell: ({ row }) => new Date(row.getValue("start_date")).toLocaleDateString()
    },
    {
      accessorKey: "end_date",
      header: "End Date",
      cell: ({ row }) => new Date(row.getValue("end_date")).toLocaleDateString()
    },
    {
      accessorKey: "stages",
      header: "Stages",
      enableSorting: false,
      cell: ({ row }) => {
        const stages = row.original.stages ?? [];
        if (stages.length === 0) {
          return <span className="text-muted-foreground">No stages</span>;
        }

        const stagesLabel = formatTournamentStages(stages);

        return (
          <div className="max-w-80">
            <div className="font-medium">
              {stages.length} {stages.length === 1 ? "stage" : "stages"}
            </div>
            <div className="truncate text-xs text-muted-foreground" title={stagesLabel}>
              {stagesLabel}
            </div>
          </div>
        );
      }
    },
    {
      id: "actions",
      cell: ({ row }) =>
        canUpdate || canDelete ? (
          <div className="flex items-center gap-2">
            {canUpdate ? (
              <Button
                aria-label={`Edit ${row.original.name}`}
                variant="ghost"
                size="icon"
                onClick={() => handleEdit(row.original)}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            ) : null}
            {canDelete ? (
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
        title="Tournaments"
        description="Manage tournaments and their stages"
        actions={
          canCreate ? (
            <Button onClick={handleCreate}>
              <Plus className="mr-2 h-4 w-4" />
              Create Tournament
            </Button>
          ) : null
        }
      />

      <AdminDataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "tournaments",
          page,
          search,
          pageSize,
          sortField,
          sortDir
        ]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          tournamentService.getAll(null).then((data) => {
            const filtered = search
              ? data.results.filter((t) => t.name.toLowerCase().includes(search.toLowerCase()))
              : data.results;
            return { ...paginateResults(sortArray(filtered, sortField, sortDir), page, pageSize) };
          })
        }
        columns={columns}
        searchPlaceholder="Search tournaments..."
        emptyMessage="No tournaments found."
        onRowClick={(row) => router.push(`/admin/tournaments/${row.original.id}`)}
      />

      {/* Create Dialog */}
      <EntityFormDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        title="Create Tournament"
        description="Create a new tournament manually or import from Challonge"
        onSubmit={handleSubmitCreate}
        isSubmitting={isCreateSubmitting}
        submittingLabel="Creating tournament…"
        errorMessage={createErrorMessage}
        isDirty={isCreateDirty}
      >
        <Tabs
          value={createMode}
          onValueChange={(v) => {
            setCreateMode(v as "manual" | "challonge");
            createMutation.reset();
            createWithGroupsMutation.reset();
          }}
        >
          <TabsList className="w-full">
            <TabsTrigger value="manual" className="flex-1">
              Manual
            </TabsTrigger>
            <TabsTrigger value="challonge" className="flex-1">
              From Challonge
            </TabsTrigger>
          </TabsList>

          <TabsContent value="manual">
            <TournamentFormFields
              idPrefix="create-manual"
              mode="manual-create"
              value={formData}
              onChange={(next) => setFormData(next)}
              divisionGridVersions={divisionGridVersions}
              divisionGridLoading={divisionGridsQuery.isLoading}
            />
          </TabsContent>

          <TabsContent value="challonge">
            <TournamentFormFields
              idPrefix="create-challonge"
              mode="challonge-create"
              value={formData}
              onChange={(next) => setFormData(next)}
              challongeSlugValue={challongeSlug}
              onChallongeSlugValueChange={setChallongeSlug}
              divisionGridVersions={divisionGridVersions}
              divisionGridLoading={divisionGridsQuery.isLoading}
            />
          </TabsContent>
        </Tabs>
      </EntityFormDialog>

      {/* Edit Dialog */}
      <EntityFormDialog
        open={editDialogOpen}
        onOpenChange={setEditDialogOpen}
        title="Edit Tournament"
        description="Update tournament details"
        onSubmit={handleSubmitUpdate}
        isSubmitting={updateMutation.isPending}
        submittingLabel="Updating tournament…"
        errorMessage={updateMutation.isError ? updateMutation.error.message : undefined}
        isDirty={isEditDirty}
      >
        <TournamentFormFields
          idPrefix="edit"
          mode="edit"
          value={formData}
          onChange={(next) => setFormData(next)}
        />
      </EntityFormDialog>

      {/* Delete Dialog */}
      {canDelete ? (
        <DeleteConfirmDialog
          open={deleteDialogOpen}
          onOpenChange={setDeleteDialogOpen}
          onConfirm={handleConfirmDelete}
          title="Delete Tournament"
          description={`Are you sure you want to delete "${selectedTournament?.name}"? This action cannot be undone.`}
          cascadeInfo={[
            "All tournament stages",
            "All teams in this tournament",
            "All players in these teams",
            "All encounters in this tournament",
            "All standings data"
          ]}
          isDeleting={deleteMutation.isPending}
        />
      ) : null}
    </div>
  );
}
