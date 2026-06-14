"use client";

import { useState } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, Plus, Pencil, Trash2, RefreshCw } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

import adminService from "@/services/admin.service";
import type { Gamemode, GamemodeCreateInput, GamemodeUpdateInput } from "@/types/admin.types";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import { useWorkspaceStore } from "@/stores/workspace.store";

const emptyGamemodeForm: GamemodeCreateInput = { name: "" };

export default function GamemodesAdminPage() {
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingGamemode, setEditingGamemode] = useState<Gamemode | null>(null);
  const [deletingGamemode, setDeletingGamemode] = useState<Gamemode | null>(null);
  const [formData, setFormData] = useState<GamemodeCreateInput | GamemodeUpdateInput>({
    ...emptyGamemodeForm,
  });
  const canCreate = canAccessPermission("gamemode.create", workspaceId);
  const canUpdate = canAccessPermission("gamemode.update", workspaceId);
  const canDelete = canAccessPermission("gamemode.delete", workspaceId);
  const canSync = canAccessPermission("gamemode.sync", workspaceId);

  const createMutation = useMutation({
    mutationFn: (data: GamemodeCreateInput) => adminService.createGamemode(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "gamemodes"] });
      setCreateDialogOpen(false);
      setFormData({ ...emptyGamemodeForm });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: GamemodeUpdateInput }) =>
      adminService.updateGamemode(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "gamemodes"] });
      setEditingGamemode(null);
      setFormData({ ...emptyGamemodeForm });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteGamemode(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "gamemodes"] });
      setDeletingGamemode(null);
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncGamemodes(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "gamemodes"] });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingGamemode) {
      updateMutation.mutate({ id: editingGamemode.id, data: formData as GamemodeUpdateInput });
    } else {
      createMutation.mutate(formData as GamemodeCreateInput);
    }
  };

  const formInitial = editingGamemode ? { name: editingGamemode.name } : emptyGamemodeForm;
  const isFormDirty = (createDialogOpen || !!editingGamemode) && hasUnsavedChanges(formData, formInitial);

  const columns: ColumnDef<Gamemode>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 80,
    },
    {
      accessorKey: "name",
      header: "Name",
    },
    {
      id: "actions",
      size: 50,
      cell: ({ row }) => {
        const gamemode = row.original;
        if (!canUpdate && !canDelete) {
          return null;
        }
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={`Open actions for ${gamemode.name}`} variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
               {canUpdate ? (
                 <DropdownMenuItem
                   onClick={() => {
                     updateMutation.reset();
                     setEditingGamemode(gamemode);
                     setFormData({ name: gamemode.name });
                   }}
                 >
                   <Pencil className="mr-2 h-4 w-4" />
                   Edit
                 </DropdownMenuItem>
               ) : null}
               {canUpdate && canDelete ? <DropdownMenuSeparator /> : null}
               {canDelete ? (
                 <DropdownMenuItem
                   onClick={() => setDeletingGamemode(gamemode)}
                   className="text-destructive"
                 >
                   <Trash2 className="mr-2 h-4 w-4" />
                   Delete
                 </DropdownMenuItem>
               ) : null}
             </DropdownMenuContent>
           </DropdownMenu>
         );
      },
    },
  ];

  return (
    <div className="space-y-6">
      <AdminPageHeader
        title="Gamemodes"
        description="Manage game modes"
        actions={
          canSync || canCreate ? (
            <div className="flex gap-2">
              {canSync ? (
                <Button
                  variant="outline"
                  onClick={() => syncMutation.mutate()}
                  disabled={syncMutation.isPending}
                >
                  <RefreshCw
                    className={`mr-2 h-4 w-4 ${syncMutation.isPending ? "animate-spin" : ""}`}
                  />
                  Sync from Game
                </Button>
              ) : null}
              {canCreate ? (
                <Button
                  onClick={() => {
                    createMutation.reset();
                    updateMutation.reset();
                    setFormData({ ...emptyGamemodeForm });
                    setCreateDialogOpen(true);
                  }}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Create Gamemode
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      <AdminDataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => ["admin", "gamemodes", page, search, pageSize, sortField, sortDir]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.getGamemodes({ page, search, per_page: pageSize, sort: sortField ?? undefined, order: sortDir })
        }
        columns={columns}
        searchPlaceholder="Search gamemodes..."
        emptyMessage="No gamemodes found."
        onRowDoubleClick={
          canUpdate
            ? (row) => {
                const gamemode = row.original;
                updateMutation.reset();
                setEditingGamemode(gamemode);
                setFormData({ name: gamemode.name });
              }
            : undefined
        }
      />

      {/* Create/Edit Dialog */}
      <EntityFormDialog
        open={createDialogOpen || !!editingGamemode}
        onOpenChange={(open) => {
          if (!open) {
            setCreateDialogOpen(false);
            setEditingGamemode(null);
            setFormData({ ...emptyGamemodeForm });
          }
        }}
        title={editingGamemode ? "Edit Gamemode" : "Create Gamemode"}
        description={
          editingGamemode ? "Update gamemode information" : "Create a new gamemode in the game"
        }
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingGamemode ? "Updating gamemode…" : "Creating gamemode…"}
        errorMessage={
          (editingGamemode ? updateMutation.error : createMutation.error) instanceof Error
            ? (editingGamemode ? updateMutation.error : createMutation.error)?.message
            : undefined
        }
        isDirty={isFormDirty}
      >
        <div className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="name">Name</Label>
            <Input
              id="name"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              placeholder="Gamemode name"
              required
            />
          </div>
        </div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {canDelete && deletingGamemode && (
        <DeleteConfirmDialog
          open={!!deletingGamemode}
          onOpenChange={(open) => !open && setDeletingGamemode(null)}
          onConfirm={() => deleteMutation.mutate(deletingGamemode.id)}
          isDeleting={deleteMutation.isPending}
          title={`Delete ${deletingGamemode.name}?`}
          cascadeInfo={["All maps using this gamemode will also be affected"]}
        />
      )}
    </div>
  );
}
