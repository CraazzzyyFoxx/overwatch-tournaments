"use client";

import { useId, useMemo } from "react";
import { ColumnDef } from "@tanstack/react-table";
import { Pencil, Trash2 } from "lucide-react";

import { AdminDataTable, adminColumnMeta, createKebabColumn } from "@/components/data-table";
import { AssetPreview } from "@/components/admin/AssetPreview";
import { CatalogAliasesField, CatalogNameField } from "@/components/admin/CatalogFormFields";
import { CatalogToolbarActions, entityFormError, onEntityDialogClose } from "@/components/admin/CatalogToolbarActions";
import { EntityFormDialog } from "@/components/kit/EntityFormDialog";
import { createAliasesColumn } from "@/components/admin/catalog-table-columns";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import adminService from "@/services/admin.service";
import type { Hero } from "@/types/hero.types";
import type { HeroCreateInput, HeroUpdateInput } from "@/types/admin.types";
import { usePermissions } from "@/hooks/usePermissions";
import { useCatalogEntityCrud } from "@/hooks/useCatalogEntityCrud";

const HERO_ROLES = ["Tank", "Damage", "Support"];
/**
 * Overwatch blue: the form default, the color-picker fallback and the hex hint.
 *
 * Exempt from the design-token rule: `color` is a persisted hero column the
 * admin edits, so this literal is the initial *value* of a data field and is
 * also what `<input type="color">` requires — not chrome this page paints with.
 */
const DEFAULT_HERO_COLOR = "#3b82f6";
// Key order matters: `hasUnsavedChanges` compares JSON, so `getHeroForm` below
// must list the shared fields in the same order or every dialog opens dirty.
const emptyHeroForm: HeroCreateInput = {
  name: "",
  role: "Damage",
  color: DEFAULT_HERO_COLOR,
  aliases: [],
};

/** The backend sends `type`; `role` is the legacy field kept for older payloads. */
function getHeroRoleValue(hero: Hero): string {
  return hero.type || hero.role || emptyHeroForm.role;
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
    aliases: hero.aliases ?? [],
  };
}

export default function HeroesAdminPage() {
  const { isSuperuser } = usePermissions();
  const formId = useId();
  const nameFieldId = `${formId}-name`;
  const imageFieldId = `${formId}-image`;
  const roleFieldId = `${formId}-role`;
  const colorFieldId = `${formId}-color`;
  const colorPickerId = `${formId}-color-picker`;
  const aliasesFieldId = `${formId}-aliases`;

  const {
    formData,
    setFormData,
    editingEntity: editingHero,
    deletingEntity: deletingHero,
    setDeletingEntity: setDeletingHero,
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
  } = useCatalogEntityCrud<Hero, HeroCreateInput, HeroUpdateInput>({
    queryKey: ["admin", "heroes"],
    emptyForm: emptyHeroForm,
    getForm: getHeroForm,
    service: {
      create: (data) => adminService.createHero(data),
      update: (id, data) => adminService.updateHero(id, data),
      delete: (id) => adminService.deleteHero(id),
      sync: () => adminService.syncHeroes(),
    },
  });

  const filterDefs = useMemo<FilterDef[]>(
    () => [
      {
        key: "role",
        label: "Role",
        kind: "single",
        options: HERO_ROLES.map((role) => ({ value: role, label: role })),
      },
    ],
    []
  );
  const filters = useFilters(filterDefs);
  const roleFilter = String(filters.values.role ?? "");

  const columns: ColumnDef<Hero>[] = [
    {
      accessorKey: "id",
      header: "ID",
      size: 44,
      cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>,
    },
    {
      id: "icon",
      header: "Icon",
      size: 52,
      meta: adminColumnMeta<Hero>({ align: "center" }),
      cell: ({ row }) => {
        const hero = row.original;
        return (
          <AssetPreview
            imagePath={hero.image_path}
            name={hero.name}
            assetLabel="hero icon"
            shape="circle"
            className="mx-auto h-10 w-10"
          />
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
                role="img"
                aria-label={`Hero color ${hero.color}`}
                title={hero.color}
                className="h-4 w-4 rounded-full border border-border"
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
      header: "Role",
      size: 48,
      meta: adminColumnMeta<Hero>({ align: "center" }),
      cell: ({ row }) => {
        const role = getHeroRoleValue(row.original);
        return (
          <div title={role}>
            <PlayerRoleIcon role={role} size={22} decorative />
            <span className="sr-only">{role}</span>
          </div>
        );
      },
    },
    createAliasesColumn<Hero>((hero) => hero.aliases),
    createKebabColumn<Hero>(
      (hero) => [
        {
          label: "Edit hero",
          icon: Pencil,
          hidden: !isSuperuser,
          onSelect: () => openEdit(hero),
        },
        {
          label: "Delete hero",
          icon: Trash2,
          destructive: true,
          hidden: !isSuperuser,
          onSelect: () => setDeletingHero(hero),
        },
      ],
      { rowLabel: (hero) => hero.name }
    ),
  ];

  return (
    <>
      <AdminDataTable
        queryKey={(page, search, pageSize, sortField, sortDir) => ["admin", "heroes", page, search, pageSize, sortField, sortDir, roleFilter]}
        queryFn={(page, search, pageSize, sortField, sortDir) =>
          adminService.getHeroes({
            page,
            search,
            per_page: pageSize,
            role: roleFilter || undefined,
            sort: sortField ?? undefined,
            order: sortDir,
          })
        }
        columns={columns}
        searchPlaceholder="Search heroes…"
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        emptyMessage="No heroes yet. Use “Create hero” to add the first one."
        onRowDoubleClick={isSuperuser ? (row) => openEdit(row.original) : undefined}
        actions={
          <CatalogToolbarActions
            canSync={isSuperuser}
            isSyncing={syncMutation.isPending}
            onSync={() => syncMutation.mutate()}
            syncLabel="Sync heroes from game"
            onCreate={openCreate}
            createLabel="Create hero"
          />
        }
      />

      {/* Create/Edit Dialog */}
      <EntityFormDialog
        open={isDialogOpen}
        onOpenChange={onEntityDialogClose(closeForm)}
        title={editingHero ? "Edit hero" : "Create hero"}
        description={editingHero ? "Update hero information" : "Create a new hero in the game"}
        onSubmit={handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingHero ? "Updating hero…" : "Creating hero…"}
        errorMessage={entityFormError(
          "hero",
          !!editingHero,
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
            placeholder="Hero name"
          />

          <div className="space-y-2">
            <Label htmlFor={imageFieldId}>Hero icon URL</Label>
            <div className="flex items-center gap-3">
              <AssetPreview
                imagePath={formData.image_path}
                name={formData.name || "Hero"}
                assetLabel="hero icon"
                shape="circle"
                className="h-10 w-10 shrink-0"
              />
              <Input
                id={imageFieldId}
                type="url"
                value={formData.image_path || ""}
                onChange={(e) => setFormData({ ...formData, image_path: e.target.value })}
                placeholder="https://overfast.craazzzyyfoxx.me/static/heroes/ana.png"
                className="flex-1"
              />
            </div>
            <p className="text-xs text-muted-foreground">Direct link to the hero portrait.</p>
          </div>

          <div className="space-y-2">
            <Label htmlFor={roleFieldId}>Role *</Label>
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg border border-border/70 bg-muted/20">
                <PlayerRoleIcon role={formData.role || emptyHeroForm.role} size={20} />
              </div>
              <Select
                value={formData.role}
                onValueChange={(value) => setFormData({ ...formData, role: value })}
              >
                <SelectTrigger id={roleFieldId} className="flex-1">
                  <SelectValue placeholder="Select role" />
                </SelectTrigger>
                <SelectContent>
                  {HERO_ROLES.map((role) => (
                    <SelectItem key={role} value={role}>
                      <div className="flex items-center gap-2">
                        <PlayerRoleIcon role={role} size={16} decorative />
                        <span>{role}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor={colorFieldId}>Color</Label>
            <div className="flex items-center gap-2">
              <Input
                id={colorPickerId}
                aria-label="Pick hero color"
                type="color"
                value={formData.color || DEFAULT_HERO_COLOR}
                onChange={(e) => setFormData({ ...formData, color: e.target.value })}
                className="h-10 w-14 shrink-0 cursor-pointer p-1"
              />
              <Input
                id={colorFieldId}
                type="text"
                value={formData.color || ""}
                onChange={(e) => setFormData({ ...formData, color: e.target.value })}
                placeholder={DEFAULT_HERO_COLOR}
                className="flex-1 font-mono"
              />
            </div>
          </div>

          <CatalogAliasesField
            id={aliasesFieldId}
            aliases={formData.aliases}
            onChange={(aliases) => setFormData({ ...formData, aliases })}
            placeholder={"Ана\nアナ"}
            helperText={
              <>
                One alias per line — names as they appear in match logs. The hero sync fills
                these from every Blizzard locale; manual entries survive it.
              </>
            }
          />
        </div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {deletingHero && (
        <ConfirmDialog
          open={!!deletingHero}
          onOpenChange={(open) => !open && setDeletingHero(null)}
          onConfirm={() => deleteMutation.mutate(deletingHero.id)}
          pending={deleteMutation.isPending}
          intent={{
            title: "Delete hero",
            description: `“${deletingHero.name}” will be permanently removed from the hero catalogue. This cannot be undone.`,
            confirmLabel: deleteMutation.isPending ? "Deleting…" : "Delete",
            tone: "danger",
          }}
        />
      )}
    </>
  );
}
