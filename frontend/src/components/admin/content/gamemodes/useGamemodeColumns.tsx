"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";

import { columnMeta } from "@craazzzyyfoxx/admin-kit/data-table";
import { AssetPreview } from "@/components/admin/AssetPreview";
import type { CatalogEntityRead } from "@/types/catalog.types";

import { useCatalogTrailingColumns } from "../shared";

export function useGamemodeColumns({
  kindLabel,
  isSuperuser,
  onEdit,
  onDelete,
}: Readonly<{
  kindLabel: string;
  isSuperuser: boolean;
  onEdit: (mode: CatalogEntityRead) => void;
  onDelete: (mode: CatalogEntityRead) => void;
}>): ColumnDef<CatalogEntityRead>[] {
  const t = useTranslations("adminWorkspace.content");
  const trailing = useCatalogTrailingColumns({ kindLabel, isSuperuser, onEdit, onDelete });
  return useMemo<ColumnDef<CatalogEntityRead>[]>(
    () => [
      {
        id: "image",
        header: t("columns.image"),
        size: 72,
        meta: columnMeta<CatalogEntityRead>({ align: "center" }),
        cell: ({ row }) => (
          <AssetPreview
            imagePath={row.original.image_path}
            name={row.original.name}
            assetLabel={t("columns.image")}
            className="mx-auto h-10 w-10"
          />
        ),
      },
      {
        accessorKey: "name",
        header: t("columns.name"),
      },
      ...trailing,
    ],
    [t, trailing]
  );
}
