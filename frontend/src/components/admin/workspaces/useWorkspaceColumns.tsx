"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { EyeOff, Pencil, Trash2, XCircle } from "lucide-react";

import { columnMeta, createKebabColumn } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { WorkspaceVerificationIcon } from "@/components/admin/workspace-verification";
import type { WorkspaceListItem } from "@/types/workspace.types";

import { WorkspaceIcon } from "./WorkspaceCells";

/** The workspace row: who it is, where it lives, and whether it is live and listed. */
export function useWorkspaceColumns({
  isSuperuser,
  isWorkspaceAdmin,
  onDelete
}: Readonly<{
  isSuperuser: boolean;
  isWorkspaceAdmin: (workspaceId: number) => boolean;
  /** Stable identity required: the kebab column closes over it. */
  onDelete: (workspace: WorkspaceListItem) => void;
}>): ColumnDef<WorkspaceListItem>[] {
  const t = useTranslations("adminAccess.common");
  return useMemo<ColumnDef<WorkspaceListItem>[]>(
    () => [
      {
        accessorKey: "id",
        header: "#",
        size: 76,
        cell: ({ row }) => (
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {row.original.id}
          </span>
        )
      },
      {
        accessorKey: "name",
        header: t("workspace"),
        cell: ({ row }) => (
          <div className="flex min-w-0 items-center gap-2">
            <WorkspaceIcon workspace={row.original} />
            {isSuperuser || isWorkspaceAdmin(row.original.id) ? (
              <Link
                href={workspaceHref(row.original.id)}
                className="truncate font-medium underline-offset-2 hover:underline"
                title={row.original.name}
              >
                {row.original.name}
              </Link>
            ) : (
              <span className="truncate font-medium" title={row.original.name}>
                {row.original.name}
              </span>
            )}
            <WorkspaceVerificationIcon status={row.original.verification_status} />
          </div>
        )
      },
      {
        accessorKey: "slug",
        header: t("slug"),
        cell: ({ row }) => (
          <span className="font-mono text-xs text-muted-foreground">{row.original.slug}</span>
        )
      },
      {
        accessorKey: "is_active",
        header: t("status"),
        size: 120,
        meta: columnMeta<WorkspaceListItem>({ align: "center" }),
        // Active is the norm; only an inactive workspace is marked.
        cell: ({ row }) =>
          row.original.is_active ? null : (
            <StatusIcon icon={XCircle} label={t("inactive")} variant="muted" />
          )
      },
      {
        accessorKey: "is_hidden",
        header: t("visibility"),
        size: 120,
        meta: columnMeta<WorkspaceListItem>({ align: "center" }),
        // Listed is the norm; only a hidden workspace is marked.
        cell: ({ row }) =>
          row.original.is_hidden ? (
            <StatusIcon icon={EyeOff} label={t("hidden")} variant="warning" />
          ) : null
      },
      createKebabColumn<WorkspaceListItem>(
        (row) => [
          {
            label: t("editWorkspace"),
            icon: Pencil,
            hidden: !(isSuperuser || isWorkspaceAdmin(row.id)),
            href: workspaceHref(row.id)
          },
          {
            label: t("deleteWorkspace"),
            icon: Trash2,
            destructive: true,
            hidden: !isSuperuser,
            onSelect: () => onDelete(row)
          }
        ],
        { rowLabel: (row) => row.name }
      )
    ],
    [isSuperuser, isWorkspaceAdmin, onDelete, t]
  );
}

/** The one place a workspace is edited: the settings sections under `[id]/`, the same ones `/admin/settings` mounts. */
export const workspaceHref = (workspaceId: number) => `/admin/workspaces/${workspaceId}/general`;
