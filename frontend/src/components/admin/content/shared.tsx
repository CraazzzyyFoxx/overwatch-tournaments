"use client";

/**
 * What the character, map and mode screens render identically: the columns every catalogue table ends with and
 * the create/edit + delete dialogs around each screen's own form fields.
 */

import { useMemo, type FormEvent, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";
import { CircleCheck, CircleSlash, Pencil, Trash2 } from "lucide-react";

import { columnMeta, createKebabColumn } from "@craazzzyyfoxx/admin-kit/data-table";
import { createAliasesColumn } from "@/components/admin/catalog-table-columns";
import { entityFormError, onEntityDialogClose } from "@/components/admin/CatalogToolbarActions";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { ConfirmDialog } from "@craazzzyyfoxx/admin-kit/kit/ConfirmDialog";
import { EntityFormDialog } from "@craazzzyyfoxx/admin-kit/kit/EntityFormDialog";
import type { FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import type { CatalogEntityRead } from "@/types/catalog.types";

/** Active / inactive: the chip every catalogue screen offers. The value goes out as `?active=`. */
export function activeFilterDef(t: (key: "filters.status" | "columns.active" | "catalog.inactive") => string): FilterDef {
  return {
    key: "active",
    label: t("filters.status"),
    kind: "single",
    options: [
      { value: "true", label: t("columns.active") },
      { value: "false", label: t("catalog.inactive") },
    ],
  };
}

/** Active, aliases, then edit/delete. */
export function useCatalogTrailingColumns({
  kindLabel,
  isSuperuser,
  onEdit,
  onDelete,
}: Readonly<{
  kindLabel: string;
  isSuperuser: boolean;
  onEdit: (entity: CatalogEntityRead) => void;
  onDelete: (entity: CatalogEntityRead) => void;
}>): ColumnDef<CatalogEntityRead>[] {
  const t = useTranslations("adminWorkspace.content");
  return useMemo<ColumnDef<CatalogEntityRead>[]>(
    () => [
      {
        accessorKey: "active",
        header: t("columns.active"),
        size: 72,
        enableSorting: false,
        meta: columnMeta<CatalogEntityRead>({ align: "center" }),
        cell: ({ row }) =>
          row.original.active ? (
            <StatusIcon icon={CircleCheck} label={t("columns.active")} variant="success" />
          ) : (
            <StatusIcon icon={CircleSlash} label={t("catalog.inactive")} variant="muted" />
          ),
      },
      createAliasesColumn<CatalogEntityRead>((entity) => entity.aliases, t("columns.aliases")),
      createKebabColumn<CatalogEntityRead>(
        (entity) => [
          {
            label: t("actions.edit", { kind: kindLabel }),
            icon: Pencil,
            hidden: !isSuperuser,
            onSelect: () => onEdit(entity),
          },
          {
            label: t("actions.deleteKind", { kind: kindLabel }),
            icon: Trash2,
            destructive: true,
            hidden: !isSuperuser,
            onSelect: () => onDelete(entity),
          },
        ],
        { rowLabel: (entity) => entity.name }
      ),
    ],
    [t, kindLabel, isSuperuser, onEdit, onDelete]
  );
}

/** The part of `useCatalogEntityCrud`'s result the dialogs read; a screen passes the whole result. */
interface CatalogEntityDialogsCrud {
  isDialogOpen: boolean;
  closeForm: () => void;
  editingEntity: CatalogEntityRead | null;
  handleSubmit: (e: FormEvent) => void;
  isFormDirty: boolean;
  createMutation: { isPending: boolean; error: unknown };
  updateMutation: { isPending: boolean; error: unknown };
  deletingEntity: CatalogEntityRead | null;
  setDeletingEntity: (entity: CatalogEntityRead | null) => void;
  deleteEntity: (id: number) => void;
  deleteMutation: { isPending: boolean };
}

/** The create/edit dialog around a screen's own form fields (`children`), and the delete confirmation. */
export function CatalogEntityDialogs({
  crud,
  kindLabel,
  children,
}: Readonly<{ crud: CatalogEntityDialogsCrud; kindLabel: string; children: ReactNode }>) {
  const t = useTranslations("adminWorkspace.content");
  const { editingEntity, deletingEntity, setDeletingEntity, createMutation, updateMutation, deleteMutation } = crud;

  return (
    <>
      {/* Create/Edit Dialog */}
      <EntityFormDialog
        open={crud.isDialogOpen}
        onOpenChange={onEntityDialogClose(crud.closeForm)}
        title={
          editingEntity
            ? t("catalog.entity.updateTitle", { kind: kindLabel })
            : t("catalog.entity.createTitle", { kind: kindLabel })
        }
        onSubmit={crud.handleSubmit}
        isSubmitting={createMutation.isPending || updateMutation.isPending}
        submittingLabel={editingEntity ? undefined : t("catalog.entity.creating")}
        errorMessage={entityFormError(
          kindLabel,
          !!editingEntity,
          updateMutation.error,
          createMutation.error,
          (key, values) => t(key, values)
        )}
        isDirty={crud.isFormDirty}
      >
        <div className="space-y-4">{children}</div>
      </EntityFormDialog>

      {/* Delete Confirmation */}
      {deletingEntity && (
        <ConfirmDialog
          open={!!deletingEntity}
          onOpenChange={(open) => !open && setDeletingEntity(null)}
          onConfirm={() => crud.deleteEntity(deletingEntity.id)}
          pending={deleteMutation.isPending}
          intent={{
            title: t("catalog.entity.deleteTitle", { kind: kindLabel }),
            description: t("catalog.entity.deleteDescription", { name: deletingEntity.name }),
            confirmLabel: t("actions.delete"),
            tone: "danger",
          }}
        />
      )}
    </>
  );
}
