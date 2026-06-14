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

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import adminService from "@/services/admin.service";
import type { Hero } from "@/types/hero.types";
import type { HeroCreateInput, HeroUpdateInput } from "@/types/admin.types";
import { usePermissions } from "@/hooks/usePermissions";
import { hasUnsavedChanges } from "@/lib/form-change";
import { useWorkspaceStore } from "@/stores/workspace.store";

const HERO_ROLES = ["Tank", "Damage", "Support"];
const emptyHeroForm: HeroCreateInput = {
  name: "",
  role: "Damage",
  color: "#3b82f6",
  image_path: "",
};

function getHeroRoleValue(hero: { role?: string | null; type?: string | null }): string {
  return hero.type || hero.role || emptyHeroForm.role;
}

function HeroIconPreview({
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
        aria-label={name ? `${name} icon placeholder` : "Hero icon placeholder"}
        className={`${className} flex items-center justify-center rounded-full border border-dashed border-border/70 bg-muted/30 text-sm font-semibold text-muted-foreground`}
      >
        {fallbackLabel}
      </div>
    );
  }

  return (
    <div
      role="img"
      aria-label={name ? `${name} icon` : "Hero icon"}
      className={`${className} rounded-full border border-border/70 bg-muted/20 bg-cover bg-center`}
      style={{ backgroundImage: `url("${imagePath}")`, backgroundPosition: "center", backgroundSize: "cover" }}
    />
  );
}

function getHeroForm(hero: Hero | null): HeroCreateInput | HeroUpdateInput {
  if (!hero) {
    return { ...emptyHeroForm };
  }

  return {
    name: hero.name,
    role: getHeroRoleValue(hero),
    color: hero.color,
    image_path: hero.image_path,
  };
}

export default function HeroesAdminPage() {
  const queryClient = useQueryClient();
  const { canAccessPermission } = usePermissions();
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [editingHero, setEditingHero] = useState<Hero | null>(null);
  const [deletingHero, setDeletingHero] = useState<Hero | null>(null);
  const [formData, setFormData] = useState<HeroCreateInput | HeroUpdateInput>({
    ...emptyHeroForm,
  });
  const canCreate = canAccessPermission("hero.create", workspaceId);
  const canUpdate = canAccessPermission("hero.update", workspaceId);
  const canDelete = canAccessPermission("hero.delete", workspaceId);
  const canSync = canAccessPermission("hero.sync", workspaceId);

  const createMutation = useMutation({
    mutationFn: (data: HeroCreateInput) => adminService.createHero(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "heroes"] });
      setCreateDialogOpen(false);
      setFormData({ ...emptyHeroForm });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: HeroUpdateInput }) =>
      adminService.updateHero(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "heroes"] });
      setEditingHero(null);
      setFormData({ ...emptyHeroForm });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => adminService.deleteHero(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "heroes"] });
      setDeletingHero(null);
    },
  });

  const syncMutation = useMutation({
    mutationFn: () => adminService.syncHeroes(),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin", "heroes"] });
    },
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (editingHero) {
      updateMutation.mutate({ id: editingHero.id, data: formData as HeroUpdateInput });
    } else {
      createMutation.mutate(formData as HeroCreateInput);
    }
  };

  const formInitial = getHeroForm(editingHero);
  const isFormDirty = (createDialogOpen || !!editingHero) && hasUnsavedChanges(formData, formInitial);

  const columns: ColumnDef<Hero>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 44,
    },
    {
      id: "icon",
      header: () => <div className="text-center">Icon</div>,
      size: 52,
      cell: ({ row }) => {
        const hero = row.original;
        return (
          <div className="flex justify-center">
            <HeroIconPreview imagePath={hero.image_path} name={hero.name} className="h-10 w-10" />
          </div>
        );
      },
    },
    {
      accessorKey: "name",
      header: "Name",
      size: 132,
      cell: ({ row }) => {
        const hero = row.original;
        return (
          <div className="flex items-center gap-2">
            {hero.color && (
              <div
                className="w-4 h-4 rounded-full border border-border"
                style={{ backgroundColor: hero.color }}
              />
            )}
            <span>{hero.name}</span>
          </div>
        );
      },
    },
    {
      id: "role",
      header: () => <div className="text-center">Role</div>,
      size: 48,
      cell: ({ row }) => {
        const role = getHeroRoleValue(row.original);
        return (
          <div className="flex justify-center">
            <div title={role}>
              <PlayerRoleIcon role={role} size={22} />
              <span className="sr-only">{role}</span>
            </div>
          </div>
        );
      },
    },
    {
      id: "actions",
      size: 50,
      cell: ({ row }) => {
        const hero = row.original;
        if (!canUpdate && !canDelete) {
          return null;
        }

        return (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button aria-label={`Open actions for ${hero.name}`} variant="ghost" size="icon">
                <MoreHorizontal className="h-4 w-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Actions</DropdownMenuLabel>
               {canUpdate ? (
                  <DropdownMenuItem
                    onClick={() => {
                      updateMutation.reset();
                      setEditingHero(hero);
                      setFormData(getHeroForm(hero));
                    }}
                  >
                    <Pencil className="mr-2 h-4 w-4" />
                    Edit
                 </DropdownMenuItem>
               ) : null}
               {canUpdate && canDelete ? <DropdownMenuSeparator /> : null}
               {canDelete ? (
                 <DropdownMenuItem onClick={() => setDeletingHero(hero)} className="text-destructive">
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
        title="Heroes"
        description="Manage game heroes and their roles"
        actions={
          canSync || canCreate ? (
            <div className="flex gap-2">
              {canSync ? (
                <Button
                  variant="outline"
                  onClick={() => syncMutation.mutate()}
                  disabled={syncMutation.isPending}
                >
                  <RefreshCw className={`mr-2 h-4 w-4 ${syncMutation.isPending ? "animate-spin" : ""}`} />
                  Sync from Game
                </Button>
              ) : null}
              {canCreate ? (
                <Button
                  onClick={() => {
                    createMutation.reset();
                    updateMutation.reset();
                    setFormData({ ...emptyHeroForm });
                    setCreateDialogOpen(true);
                  }}
                >
                  <Plus className="mr-2 h-4 w-4" />
                  Create Hero
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      <AdminDataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => ["admin", "heroes", page, search, pageSize, sortField, sortDir]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.getHeroes({ page, search, per_page: pageSize, sort: sortField ?? undefined, order: sortDir })
        }
        columns={columns}
        searchPlaceholder="Search heroes..."
        emptyMessage="No heroes found."
        onRowDoubleClick={
          canUpdate
            ? (row) => {
                const hero = row.original;
                updateMutation.reset();
                setEditingHero(hero);
                setFormData(getHeroForm(hero));
              }
            : undefined
        }
      />

      {/* Create/Edit Dialog */}
      <EntityFormDialog
        open={createDialogOpen || !!editingHero}
        onOpenChange={(open) => {
          if (!open) {
            setCreateDialogOpen(false);
            setEditingHero(null);
            setFormData({ ...emptyHeroForm });
          }
        }}
        title={editingHero ? "Edit Hero" : "Create Hero"}
        description={editingHero ? "Update hero information" : "Create a new hero in the game"}
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingHero ? "Updating hero…" : "Creating hero…"}
        errorMessage={
          (editingHero ? updateMutation.error : createMutation.error) instanceof Error
            ? (editingHero ? updateMutation.error : createMutation.error)?.message
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
              placeholder="Hero name"
              required
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="image_path">Hero icon</Label>
            <div className="flex items-start gap-3">
              <HeroIconPreview
                imagePath={formData.image_path}
                name={formData.name || "Hero"}
                className="h-16 w-16 shrink-0"
              />
              <div className="flex-1 space-y-2">
                <Input
                  id="image_path"
                  type="url"
                  value={formData.image_path || ""}
                  onChange={(e) => setFormData({ ...formData, image_path: e.target.value })}
                  placeholder="https://overfast.craazzzyyfoxx.me/static/heroes/ana.png"
                />
                <p className="text-xs text-muted-foreground">
                  Use a direct URL to the hero portrait shown in the admin table and user pages.
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="role">Role</Label>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-border/70 bg-muted/20">
                <PlayerRoleIcon role={formData.role || emptyHeroForm.role} size={20} />
              </div>
              <Select
                value={formData.role}
                onValueChange={(value) => setFormData({ ...formData, role: value })}
              >
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Select role" />
                </SelectTrigger>
                <SelectContent>
                  {HERO_ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                      <div className="flex items-center gap-2">
                        <PlayerRoleIcon role={role} size={16} />
                        <span>{role}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="color">Color</Label>
            <div className="flex items-center gap-2">
              <Input
                id="color"
                type="color"
                value={formData.color || "#3b82f6"}
                onChange={(e) => setFormData({ ...formData, color: e.target.value })}
                className="w-20 h-10 cursor-pointer"
              />
              <Input
                type="text"
                value={formData.color || ""}
                onChange={(e) => setFormData({ ...formData, color: e.target.value })}
                placeholder="#3b82f6"
                className="flex-1"
              />
            </div>
          </div>
        </div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {canDelete && deletingHero && (
        <DeleteConfirmDialog
          open={!!deletingHero}
          onOpenChange={(open) => !open && setDeletingHero(null)}
          onConfirm={() => deleteMutation.mutate(deletingHero.id)}
          isDeleting={deleteMutation.isPending}
          title={`Delete ${deletingHero.name}?`}
        />
      )}
    </div>
  );
}
