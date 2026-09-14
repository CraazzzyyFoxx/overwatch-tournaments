"use client";

import { useId } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { Pencil, Trash2 } from "lucide-react";

import { AdminDataTable, createKebabColumn } from "@/components/admin-data-table";
import { CatalogAliasesField, CatalogNameField } from "@/components/admin/CatalogFormFields";
import { CatalogToolbarActions, entityFormError, onEntityDialogClose } from "@/components/admin/CatalogToolbarActions";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { createAliasesColumn } from "@/components/admin/catalog-table-columns";
import { ConfirmDialog } from "@/components/admin/kit/ConfirmDialog";

import adminService from "@/services/admin.service";
import type { Gamemode, GamemodeCreateInput, GamemodeUpdateInput } from "@/types/admin.types";
import { usePermissions } from "@/hooks/usePermissions";
import { useCatalogEntityCrud } from "@/hooks/useCatalogEntityCrud";

// Key order matters: `hasUnsavedChanges` compares JSON, so the edit form below
// must list the same fields in the same order or every dialog opens dirty.
const emptyGamemodeForm: GamemodeCreateInput = { name: "", aliases: [] };

function getGamemodeForm(gamemode: Gamemode | null): GamemodeCreateInput | GamemodeUpdateInput {
  if (!gamemode) {
    return { ...emptyGamemodeForm };
  }

  return { name: gamemode.name, aliases: gamemode.aliases ?? [] };
}

export default function GamemodesAdminPage() {
  const { isSuperuser } = usePermissions();
  const formId = useId();
  const nameFieldId = `${formId}-name`;
  const aliasesFieldId = `${formId}-aliases`;

  const {
    formData,
    setFormData,
    editingEntity: editingGamemode,
    deletingEntity: deletingGamemode,
    setDeletingEntity: setDeletingGamemode,
    isDialogOpen,
    closeForm,
    openCreate,
    openEdit,
    handleSubmit,
    isFormDirty,
    createMutation,
    updateMutation,
    deleteMutation,
    syncMutation,
  } = useCatalogEntityCrud<Gamemode, GamemodeCreateInput, GamemodeUpdateInput>({
    queryKey: ["admin", "gamemodes"],
    emptyForm: emptyGamemodeForm,
    getForm: getGamemodeForm,
    service: {
      create: (data) => adminService.createGamemode(data),
      update: (id, data) => adminService.updateGamemode(id, data),
      delete: (id) => adminService.deleteGamemode(id),
      sync: () => adminService.syncGamemodes(),
    },
  });

  const columns: ColumnDef<Gamemode>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 80,
      cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>,
    },
    {
      accessorKey: "name",
      header: "Name",
    },
    createAliasesColumn<Gamemode>((gamemode) => gamemode.aliases),
    createKebabColumn<Gamemode>(
      (gamemode) => [
        {
          label: "Edit gamemode",
          icon: Pencil,
          hidden: !isSuperuser,
          onSelect: () => openEdit(gamemode),
        },
        {
          label: "Delete gamemode",
          icon: Trash2,
          destructive: true,
          hidden: !isSuperuser,
          onSelect: () => setDeletingGamemode(gamemode),
        },
      ],
      { rowLabel: (gamemode) => gamemode.name }
    ),
  ];

  return (
    <>
      <AdminDataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => ["admin", "gamemodes", page, search, pageSize, sortField, sortDir]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.getGamemodes({ page, search, per_page: pageSize, sort: sortField ?? undefined, order: sortDir })
        }
        columns={columns}
        searchPlaceholder="Search gamemodes…"
        emptyMessage="No gamemodes yet. Use “Create gamemode” to add the first one."
        onRowDoubleClick={isSuperuser ? (row) => openEdit(row.original) : undefined}
        actions={
          <CatalogToolbarActions
            canSync={isSuperuser}
            isSyncing={syncMutation.isPending}
            onSync={() => syncMutation.mutate()}
            syncLabel="Sync gamemodes from game"
            onCreate={openCreate}
            createLabel="Create gamemode"
          />
        }
      />

      {/* Create/Edit Dialog */}
      <EntityFormDialog
        open={isDialogOpen}
        onOpenChange={onEntityDialogClose(closeForm)}
        title={editingGamemode ? "Edit gamemode" : "Create gamemode"}
        description={
          editingGamemode ? "Update gamemode information" : "Create a new gamemode in the game"
        }
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingGamemode ? "Updating gamemode…" : "Creating gamemode…"}
        errorMessage={entityFormError(
          "gamemode",
          !!editingGamemode,
          updateMutation.error,
          createMutation.error
        )}
        isDirty={isFormDirty}
      >
        <div className="space-y-4">
          <CatalogNameField
            id={nameFieldId}
            value={formData.name}
            onChange={(name) => setFormData({ ...formData, name })}
            placeholder="Gamemode name"
          />

          <CatalogAliasesField
            id={aliasesFieldId}
            aliases={formData.aliases}
            onChange={(aliases) => setFormData({ ...formData, aliases })}
            placeholder={"Контроль\nコントロール"}
            helperText="One alias per line — names as they appear in match logs."
          />
        </div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {deletingGamemode && (
        <ConfirmDialog
          open={!!deletingGamemode}
          onOpenChange={(open) => !open && setDeletingGamemode(null)}
          onConfirm={() => deleteMutation.mutate(deletingGamemode.id)}
          pending={deleteMutation.isPending}
          intent={{
            title: "Delete gamemode",
            description: `“${deletingGamemode.name}” will be permanently removed. Reassign any maps still using it first, otherwise the delete will fail.`,
            confirmLabel: deleteMutation.isPending ? "Deleting…" : "Delete",
            tone: "danger",
          }}
        />
      )}
    </>
  );
}
