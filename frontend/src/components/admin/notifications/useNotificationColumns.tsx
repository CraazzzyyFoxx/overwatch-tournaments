"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Archive } from "lucide-react";
import { useTranslations } from "next-intl";

import { StatusIcon } from "@/components/admin/StatusIcon";
import { columnMeta } from "@craazzzyyfoxx/admin-kit/data-table";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { useFormatter } from "@/lib/datetime/client";
import type { NotificationAdminItem } from "@/types/notification.types";

import { isRetired } from "./model";

/**
 * The produced-notification columns. The retire column exists only for a
 * `notification.delete` holder; `onRetire` asks for the confirmation, it does
 * not retire. The kind column is dropped while a kind filter is on: the chip
 * already says it for every row.
 */
export function useNotificationColumns({
  canRetire,
  showKind,
  retirePending,
  onRetire
}: Readonly<{
  canRetire: boolean;
  showKind: boolean;
  retirePending: boolean;
  onRetire: (target: { ids: number[] }) => void;
}>): ColumnDef<NotificationAdminItem>[] {
  const t = useTranslations<never>();
  const format = useFormatter();

  return useMemo<ColumnDef<NotificationAdminItem>[]>(() => {
    const defs: ColumnDef<NotificationAdminItem>[] = [
      {
        id: "recipient",
        header: t("notifications.workspaceAdmin.columns.recipient"),
        size: 200,
        enableSorting: false,
        // Username joined at read time, id as the fallback: the account can be
        // gone while the row it was told about still has to be retirable.
        cell: ({ row }) => (
          <span className="text-sm text-muted-foreground">
            {row.original.recipient_username ?? row.original.recipient_auth_user_id}
          </span>
        )
      },
      {
        accessorKey: "published_at",
        header: t("notifications.workspaceAdmin.columns.publishedAt"),
        size: 190,
        enableSorting: false,
        cell: ({ row }) =>
          row.original.published_at == null ? null : (
            <time dateTime={row.original.published_at} className="whitespace-nowrap text-sm tabular-nums">
              {format.dateTime(new Date(row.original.published_at), {
                dateStyle: "medium",
                timeStyle: "short"
              })}
            </time>
          )
      },
      {
        id: "state",
        header: t("notifications.workspaceAdmin.columns.state"),
        size: 90,
        enableSorting: false,
        meta: columnMeta<NotificationAdminItem>({ align: "center" }),
        // In inboxes is the norm; only the retired row is marked.
        cell: ({ row }) =>
          isRetired(row.original) ? (
            <StatusIcon
              icon={Archive}
              label={t("notifications.workspaceAdmin.state.retired")}
              variant="muted"
            />
          ) : null
      }
    ];

    if (showKind) {
      defs.unshift({
        accessorKey: "kind",
        header: t("notifications.workspaceAdmin.columns.kind"),
        size: 220,
        // One server order (newest first); a header sort would change nothing.
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-sm">
            {t(`notifications.workspaceAdmin.kinds.${row.original.kind}` as never)}
          </span>
        )
      });
    }

    if (canRetire) {
      defs.push({
        id: "actions",
        header: "",
        size: 130,
        enableSorting: false,
        cell: ({ row }) =>
          isRetired(row.original) ? null : (
            <Button
              variant="ghost"
              size="sm"
              disabled={retirePending}
              onClick={() => onRetire({ ids: [row.original.id] })}
            >
              {t("notifications.workspaceAdmin.retire.action")}
            </Button>
          )
      });
    }
    return defs;
  }, [t, format, canRetire, showKind, retirePending, onRetire]);
}
