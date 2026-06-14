"use client";

import { useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, Plus, Pencil, Trash2, RefreshCw } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { AdminPageHeader } from "@/components/admin/AdminPageHeader";
import { EntityFormDialog } from "@/components/admin/EntityFormDialog";
import { DeleteConfirmDialog } from "@/components/admin/DeleteConfirmDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Badge } from "@/components/ui/badge";

import adminService from "@/services/admin.service";
import type { MapRead } from "@/types/map.types";
import type { MapCreateInput, MapUpdateInput } from "@/types/admin.types";
import { apiFetch } from "@/lib/api-fetch";
import type { Gamemode } from "@/types/gamemode.types";
import type { PaginatedResponse } from "@/types/pagination.types";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import { useWorkspaceStore } from "@/stores/workspace.store";

const emptyMapForm: MapCreateInput = {
  name: "",
  gamemode_id: 0,
};
const GAMEMODE_QUERY_PARAM = "gamemode_id";

function parseGamemodeQueryParam(value: string | null): number | null {
  if (!value) return null;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

function MapImagePreview({
  imagePath,
  name,
  className,
}: {
  imagePath?: string | null;
  name: string;
  className: string;
}) {
  const fallbackLabel = (name.trim().charAt(0) || "?").toUpperCase();

  if (!imagePath) {
    return (
      <div
        aria-label={name ? `${name} image placeholder` : "Map image placeholder"}
        className={`${className} flex items-center justify-center rounded-md border border-dashed border-border/70 bg-muted/30 text-sm font-semibold text-muted-foreground`}
      >
        {fallbackLabel}
      </div>
    );
  }

  return (
    <div
      role="img"
      aria-label={name ? `${name} image` : "Map image"}
      className={`${className} rounded-md border border-border/70 bg-muted/20 bg-cover bg-center`}
      style={{ backgroundImage: `url("${imagePath}")` }}
    />
  );
}

export default function MapsAdminPage() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingMap, setEditingMap] = useState<MapRead | null>(null);
  const [deletingMap, setDeletingMap] = useState<MapRead | null>(null);
  const [formData, setFormData] = useState<MapCreateInput | MapUpdateInput>({
    ...emptyMapForm,
  });
  const canCreate = canAccessPermission("map.create", workspaceId);
  const canUpdate = canAccessPermission("map.update", workspaceId);
  const canDelete = canAccessPermission("map.delete", workspaceId);
  const canSync = canAccessPermission("map.sync", workspaceId);
  const selectedGamemodeId = parseGamemodeQueryParam(searchParams.get(GAMEMODE_QUERY_PARAM));

  // Fetch gamemodes for selector
  const { data: gamemodesData } = useQuery({
    queryKey: ["gamemodes"],
    queryFn: async () => {
      const response = await apiFetch("app","/gamemodes");
      const data = (await response.json()) as PaginatedResponse<Gamemode>;
      return data.results;
    },
  });

  const createMutation = useMutation({
    mutationFn: (data: MapCreateInput) => adminService.createMap(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "maps"] });
      setCreateDialogOpen(false);
      setFormData({ ...emptyMapForm });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: MapUpdateInput }) =>
      adminService.updateMap(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "maps"] });
      setEditingMap(null);
      setFormData({ ...emptyMapForm });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteMap(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "maps"] });
      setDeletingMap(null);
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncMaps(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "maps"] });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingMap) {
      updateMutation.mutate({ id: editingMap.id, data: formData as MapUpdateInput });
    } else {
      createMutation.mutate(formData as MapCreateInput);
    }
  };

  const handleGamemodeFilterChange = (value: string) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (value === "all") {
      nextParams.delete(GAMEMODE_QUERY_PARAM);
    } else {
      nextParams.set(GAMEMODE_QUERY_PARAM, value);
    }
    nextParams.delete("page");

    const query = nextParams.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  };

  const formInitial = editingMap ? { name: editingMap.name, gamemode_id: editingMap.gamemode_id } : emptyMapForm;
  const isFormDirty = (createDialogOpen || !!editingMap) && hasUnsavedChanges(formData, formInitial);

  const columns: ColumnDef<MapRead>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 44,
    },
    {
      id: "image",
      header: () => <div className="text-center">Image</div>,
      size: 96,
      cell: ({ row }) => {
        const map = row.original;
        return (
          <div className="flex justify-center">
            <MapImagePreview imagePath={map.image_path} name={map.name} className="h-12 w-24" />
          </div>
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
      id: "actions",
      size: 50,
      cell: ({ row }) => {
        const map = row.original;
        if (!canUpdate && !canDelete) {
          return null;
        }
        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={`Open actions for ${map.name}`} variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
               {canUpdate ? (
                 <DropdownMenuItem
                   onClick={() => {
                     updateMutation.reset();
                     setEditingMap(map);
                     setFormData({ name: map.name, gamemode_id: map.gamemode_id });
                   }}
                 >
                   <Pencil className="mr-2 h-4 w-4" />
                   Edit
                 </DropdownMenuItem>
               ) : null}
               {canUpdate && canDelete ? <DropdownMenuSeparator /> : null}
               {canDelete ? (
                 <DropdownMenuItem onClick={() => setDeletingMap(map)} className="text-destructive">
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
        title="Maps"
        description="Manage game maps"
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
                    setFormData({ ...emptyMapForm });
                    setCreateDialogOpen(true);
                  }}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Create Map
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      <AdminDataTable
        key={`maps-table-${selectedGamemodeId ?? "all"}`}
        queryKey={(page, search, pageSize, sortField, sortDir) => [
          "admin",
          "maps",
          selectedGamemodeId,
          page,
          search,
          pageSize,
          sortField,
          sortDir,
        ]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.getMaps({
            page,
            search,
            per_page: pageSize,
            gamemode_id: selectedGamemodeId ?? undefined,
            sort: sortField ?? undefined,
            order: sortDir,
          })
        }
        columns={columns}
        searchPlaceholder="Search maps..."
        emptyMessage="No maps found."
        actions={
          <Select
            value={selectedGamemodeId?.toString() ?? "all"}
            onValueChange={handleGamemodeFilterChange}
          >
            <SelectTrigger className="w-[220px]">
              <SelectValue placeholder="Filter by gamemode" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All gamemodes</SelectItem>
              {gamemodesData?.map((gamemode) => (
                <SelectItem key={gamemode.id} value={gamemode.id.toString()}>
                  {gamemode.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
        onRowDoubleClick={
          canUpdate
            ? (row) => {
                const map = row.original;
                updateMutation.reset();
                setEditingMap(map);
                setFormData({ name: map.name, gamemode_id: map.gamemode_id });
              }
            : undefined
        }
      />

      {/* Create/Edit Dialog */}
      <EntityFormDialog
        open={createDialogOpen || !!editingMap}
        onOpenChange={(open) => {
          if (!open) {
            setCreateDialogOpen(false);
            setEditingMap(null);
            setFormData({ ...emptyMapForm });
          }
        }}
        title={editingMap ? "Edit Map" : "Create Map"}
        description={editingMap ? "Update map information" : "Create a new map in the game"}
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingMap ? "Updating map…" : "Creating map…"}
        errorMessage={
          (editingMap ? updateMutation.error : createMutation.error) instanceof Error
            ? (editingMap ? updateMutation.error : createMutation.error)?.message
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
              placeholder="Map name"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="gamemode">Gamemode</Label>
            <Select
              value={formData.gamemode_id?.toString() || ""}
              onValueChange={(value) =>
                setFormData({ ...formData, gamemode_id: parseInt(value) })
              }
            >
              <SelectTrigger>
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
        </div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {canDelete && deletingMap && (
        <DeleteConfirmDialog
          open={!!deletingMap}
          onOpenChange={(open) => !open && setDeletingMap(null)}
          onConfirm={() => deleteMutation.mutate(deletingMap.id)}
          isDeleting={deleteMutation.isPending}
          title={`Delete ${deletingMap.name}?`}
        />
      )}
    </div>
  );
}
