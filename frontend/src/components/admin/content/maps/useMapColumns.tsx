"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";
import { Gamepad2 } from "lucide-react";

import { columnMeta } from "@craazzzyyfoxx/admin-kit/data-table";
import { AssetPreview } from "@/components/admin/AssetPreview";
import { StatusIcon } from "@/components/admin/StatusIcon";
import type { CatalogEntityRead } from "@/types/catalog.types";

import { useCatalogTrailingColumns } from "../shared";

/** The map row: thumbnail and name, plus its mode and pool when the game declares modes. */
export function useMapColumns({
  kindLabel,
  hasModes,
  modeLabel,
  isSuperuser,
  onEdit,
  onDelete,
}: Readonly<{
  kindLabel: string;
  hasModes: boolean;
  /** The game's own word for a mode, as the mode column's header. */
  modeLabel: string;
  isSuperuser: boolean;
  onEdit: (map: CatalogEntityRead) => void;
  onDelete: (map: CatalogEntityRead) => void;
}>): ColumnDef<CatalogEntityRead>[] {
  const t = useTranslations("adminWorkspace.content");
  const trailing = useCatalogTrailingColumns({ kindLabel, isSuperuser, onEdit, onDelete });
  return useMemo<ColumnDef<CatalogEntityRead>[]>(
    () => [
      {
        id: "image",
        header: t("columns.image"),
        size: 96,
        meta: columnMeta<CatalogEntityRead>({ align: "center" }),
        cell: ({ row }) => {
          const map = row.original;
          return (
            <AssetPreview
              imagePath={map.image_path}
              name={map.name}
              assetLabel={t("columns.image")}
              className="mx-auto h-12 w-24"
            />
          );
        },
      },
      {
        accessorKey: "name",
        header: t("columns.name"),
        size: 144,
      },
      ...(hasModes
        ? [
            {
              accessorKey: "parent",
              header: modeLabel,
              size: 112,
              enableSorting: false,
              cell: ({ row }) => (row.original.parent ? <span className="text-sm">{row.original.parent.name}</span> : null),
            } satisfies ColumnDef<CatalogEntityRead>,
            {
              accessorKey: "in_competitive",
              header: t("columns.modePool"),
              size: 120,
              enableSorting: false,
              meta: columnMeta<CatalogEntityRead>({ align: "center" }),
              // Most maps are in the competitive pool: only the exception is marked.
              cell: ({ row }) =>
                row.original.attrs.in_competitive === false ? (
                  <StatusIcon icon={Gamepad2} label={t("catalog.casual")} variant="muted" />
                ) : null,
            } satisfies ColumnDef<CatalogEntityRead>,
          ]
        : []),
      ...trailing,
    ],
    [t, hasModes, modeLabel, trailing]
  );
}
