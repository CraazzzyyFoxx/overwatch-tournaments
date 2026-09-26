"use client";

import { useId, useMemo } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { useQuery } from "@tanstack/react-query";
import { Gamepad2, Pencil, Swords, Trash2 } from "lucide-react";

import { DataTable, columnMeta, createKebabColumn } from "@/components/data-table";
import { AssetPreview } from "@/components/admin/AssetPreview";
import { CatalogAliasesField, CatalogNameField } from "@/components/admin/CatalogFormFields";
import { CatalogToolbarActions, entityFormError, onEntityDialogClose } from "@/components/admin/CatalogToolbarActions";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { createAliasesColumn } from "@/components/admin/catalog-table-columns";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import adminService from "@/services/admin.service";
import type { MapRead } from "@/types/map.types";
import type { MapCreateInput, MapUpdateInput } from "@/types/admin.types";
import { apiFetch } from "@/lib/api/fetch";
import type { Gamemode } from "@/types/gamemode.types";
import type { PaginatedResponse } from "@/types/pagination.types";
import { usePermissions } from "@/hooks/usePermissions";
import { useCatalogEntityCrud } from "@/hooks/useCatalogEntityCrud";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { mapQueryKeys } from "@/lib/maps/query-keys";

// Key order matters: `hasUnsavedChanges` compares JSON, so `getMapForm` below
// must list the same fields in the same order or every dialog opens dirty.
const emptyMapForm: MapCreateInput = {
  name: "",
  gamemode_id: 0,
  in_competitive: true,
  aliases: [],
};

function getMapForm(map: MapRead | null): MapCreateInput | MapUpdateInput {
  if (!map) {
    return { ...emptyMapForm };
  }

  return {
    name: map.name,
    gamemode_id: map.gamemode_id,
    in_competitive: map.in_competitive !== false,
    aliases: map.aliases ?? [],
  };
}

export default function MapsAdminPage() {
  const { isSuperuser } = usePermissions();
  const formId = useId();
  const nameFieldId = `${formId}-name`;
  const gamemodeFieldId = `${formId}-gamemode`;
  const aliasesFieldId = `${formId}-aliases`;

  // Gamemodes back both the create/edit dialog select and the Gamemode chip.
  const { data: gamemodesData } = useQuery({
    queryKey: mapQueryKeys.gamemodes(),
    queryFn: async () => {
      const response = await apiFetch("/api/v1/gamemodes");
      const data = (await response.json()) as PaginatedResponse<Gamemode>;
      return data.results;
    },
  });

  const {
    formData,
    setFormData,
    editingEntity: editingMap,
    deletingEntity: deletingMap,
    setDeletingEntity: setDeletingMap,
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
  } = useCatalogEntityCrud<MapRead, MapCreateInput, MapUpdateInput>({
    queryKey: adminQueryKeys.contentEntity("maps"),
    emptyForm: emptyMapForm,
    getForm: getMapForm,
    service: {
      create: (data) => adminService.createMap(data),
      update: (id, data) => adminService.updateMap(id, data),
      delete: (id) => adminService.deleteMap(id),
      sync: () => adminService.syncMaps(),
    },
  });

  const filterDefs = useMemo<FilterDef[]>(
    () => [
      {
        key: "gamemode_id",
        label: "Gamemode",
        kind: "single",
        options: (gamemodesData ?? []).map((gamemode) => ({
          value: gamemode.id.toString(),
          label: gamemode.name,
        })),
      },
      {
        key: "in_competitive",
        label: "Mode pool",
        kind: "single",
        options: [
          { value: "true", label: "Competitive" },
          { value: "false", label: "Casual" },
        ],
      },
    ],
    [gamemodesData]
  );
  const filters = useFilters(filterDefs);
  const gamemodeFilter = String(filters.values.gamemode_id ?? "");
  const competitiveFilter = String(filters.values.in_competitive ?? "");

  const columns: ColumnDef<MapRead>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 44,
      cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>,
    },
    {
      id: "image",
      header: "Image",
      size: 96,
      meta: columnMeta<MapRead>({ align: "center" }),
      cell: ({ row }) => {
        const map = row.original;
        return (
          <AssetPreview
            imagePath={map.image_path}
            name={map.name}
            assetLabel="map image"
            className="mx-auto h-12 w-24"
          />
        );
      },
    },
    {
      accessorKey: "name",
      header: "Name",
      size: 144,
    },
    {
      accessorKey: "gamemode",
      header: "Gamemode",
      size: 112,
      enableSorting: false,
      cell: ({ row }) => {
        const map = row.original;
        return map.gamemode ? (
          <Badge variant="outline">{map.gamemode.name}</Badge>
        ) : (
          <span className="text-sm text-muted-foreground">Unknown</span>
        );
      },
    },
    {
      accessorKey: "in_competitive",
      header: "Mode Pool",
      size: 120,
      meta: columnMeta<MapRead>({ align: "center" }),
      cell: ({ row }) => {
        const map = row.original;
        return map.in_competitive !== false ? (
          <StatusIcon icon={Swords} label="Competitive" variant="success" />
        ) : (
          <StatusIcon icon={Gamepad2} label="Casual" variant="muted" />
        );
      },
    },
    createAliasesColumn<MapRead>((map) => map.aliases),
    createKebabColumn<MapRead>(
      (map) => [
        {
          label: "Edit map",
          icon: Pencil,
          hidden: !isSuperuser,
          onSelect: () => openEdit(map),
        },
        {
          label: "Delete map",
          icon: Trash2,
          destructive: true,
          hidden: !isSuperuser,
          onSelect: () => setDeletingMap(map),
        },
      ],
      { rowLabel: (map) => map.name }
    ),
  ];

  return (
    <>
      <DataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "admin",
          "maps",
          page,
          search,
          pageSize,
          sortField,
          sortDir,
          gamemodeFilter,
          competitiveFilter,
        ]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.getMaps({
            page,
            search,
            per_page: pageSize,
            gamemode_id: gamemodeFilter ? Number(gamemodeFilter) : undefined,
            in_competitive: competitiveFilter ? competitiveFilter === "true" : undefined,
            sort: sortField ?? undefined,
            order: sortDir,
          })
        }
        columns={columns}
        searchPlaceholder="Search maps…"
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        emptyMessage="No maps yet. Use “Create map” to add the first one."
        onRowDoubleClick={isSuperuser ? (row) => openEdit(row.original) : undefined}
        actions={
          <CatalogToolbarActions
            canSync={isSuperuser}
            isSyncing={syncMutation.isPending}
            onSync={() => syncMutation.mutate()}
            syncLabel="Sync maps from game"
            onCreate={openCreate}
            createLabel="Create map"
          />
        }
      />

      {/* Create/Edit Dialog */}
      <EntityFormDialog
        open={isDialogOpen}
        onOpenChange={onEntityDialogClose(closeForm)}
        title={editingMap ? "Edit map" : "Create map"}
        description={editingMap ? "Update map information" : "Create a new map in the game"}
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingMap ? "Updating map…" : "Creating map…"}
        errorMessage={entityFormError(
          "map",
          !!editingMap,
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
            placeholder="Map name"
          />

          <div className="space-y-2">
            <Label htmlFor={gamemodeFieldId}>Gamemode *</Label>
            <Select
              value={formData.gamemode_id?.toString() || ""}
              onValueChange={(value) =>
                setFormData({ ...formData, gamemode_id: parseInt(value) })
              }
            >
              <SelectTrigger id={gamemodeFieldId}>
                <SelectValue placeholder="Select gamemode" />
              </SelectTrigger>
              <SelectContent>
                {gamemodesData?.map((gamemode) => (
                  <SelectItem key={gamemode.id} value={gamemode.id.toString()}>
                    {gamemode.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <CatalogAliasesField
            id={aliasesFieldId}
            aliases={formData.aliases}
            onChange={(aliases) => setFormData({ ...formData, aliases })}
            placeholder={"Илиос\nHollywood (Halloween)"}
            helperText="One alias per line — names as they appear in match logs."
          />

          <div className="flex items-center gap-2 pt-2">
            <Checkbox
              id={`${formId}-in-competitive`}
              checked={formData.in_competitive !== false}
              onCheckedChange={(checked) =>
                setFormData({ ...formData, in_competitive: Boolean(checked) })
              }
            />
            <Label htmlFor={`${formId}-in-competitive`} className="cursor-pointer font-medium text-sm">
              Competitive map (Входит в соревновательный пул)
            </Label>
          </div>
        </div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {deletingMap && (
        <ConfirmDialog
          open={!!deletingMap}
          onOpenChange={(open) => !open && setDeletingMap(null)}
          onConfirm={() => deleteMutation.mutate(deletingMap.id)}
          pending={deleteMutation.isPending}
          intent={{
            title: "Delete map",
            description: `“${deletingMap.name}” will be permanently removed from the map catalogue. This cannot be undone.`,
            confirmLabel: deleteMutation.isPending ? "Deleting…" : "Delete",
            tone: "danger",
          }}
        />
      )}
    </>
  );
}
