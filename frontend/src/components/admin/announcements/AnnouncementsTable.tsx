"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Archive, CircleDot, Clock } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";

import { AdminDataTable, adminColumnMeta } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { announcementText } from "@/lib/notifications/announcement-text";
import type { NotificationItem } from "@/types/notification.types";

import { announcementState } from "./announcement-draft";

interface AnnouncementsTableProps {
  rows: NotificationItem[];
  isLoading: boolean;
  /** Absent when the operator may read this feed but not write to it. */
  onRetire?: (row: NotificationItem) => void;
  isRetiring: boolean;
}

const STATE_ICON = {
  active: { icon: CircleDot, variant: "success" },
  scheduled: { icon: Clock, variant: "info" },
  retired: { icon: Archive, variant: "muted" },
} as const;

export function AnnouncementsTable({
  rows,
  isLoading,
  onRetire,
  isRetiring,
}: Readonly<AnnouncementsTableProps>) {
  const t = useTranslations<never>();
  const locale = useLocale();
  const format = useFormatter();
  const [confirming, setConfirming] = useState<NotificationItem | null>(null);

  const columns = useMemo<ColumnDef<NotificationItem>[]>(() => {
    const stamp = (value: string | null) =>
      value == null ? (
        <span className="text-sm text-muted-foreground">&mdash;</span>
      ) : (
        <time dateTime={value} className="whitespace-nowrap text-sm tabular-nums">
          {format.dateTime(new Date(value), { dateStyle: "medium", timeStyle: "short" })}
        </time>
      );

    const list: ColumnDef<NotificationItem>[] = [
      {
        id: "title",
        header: t("notifications.admin.columns.title"),
        cell: ({ row }) => (
          <span className="text-sm font-medium">
            {/* The operator's own language, falling back to the one it was
                written in — a workspace announcement may carry only one. */}
            {announcementText(row.original.payload, locale)?.title ??
              t("notifications.admin.untitled")}
          </span>
        ),
      },
      {
        accessorKey: "audience",
        header: t("notifications.admin.columns.audience"),
        size: 140,
        // Two values, spelled out: `user` is a member of the wire type but not
        // of this feed (the RPC scopes it to `workspace`/`global`), and an
        // interpolated key would claim a message that does not exist.
        cell: ({ row }) => (
          <Badge
            tone={row.original.audience === "global" ? "info" : "neutral"}
            className="font-normal"
          >
            {row.original.audience === "global"
              ? t("notifications.admin.audience.global")
              : t("notifications.admin.audience.workspace")}
          </Badge>
        ),
      },
      {
        accessorKey: "published_at",
        header: t("notifications.admin.columns.publishedAt"),
        size: 190,
        cell: ({ row }) => stamp(row.original.published_at),
      },
      {
        accessorKey: "expires_at",
        header: t("notifications.admin.columns.expiresAt"),
        size: 190,
        cell: ({ row }) => stamp(row.original.expires_at),
      },
      {
        id: "state",
        header: t("notifications.admin.columns.state"),
        size: 130,
        enableSorting: false,
        meta: adminColumnMeta({ align: "center" }),
        // Read off the two stamps rather than asked of the backend: the reads
        // themselves filter on that window, so a stored flag could disagree
        // with who actually sees the row.
        cell: ({ row }) => {
          const state = announcementState(row.original);
          const meta = STATE_ICON[state];
          return (
            <StatusIcon
              icon={meta.icon}
              label={t(`notifications.admin.state.${state}`)}
              variant={meta.variant}
            />
          );
        },
      },
    ];

    if (onRetire) {
      list.push({
        id: "actions",
        header: "",
        size: 130,
        enableSorting: false,
        cell: ({ row }) =>
          announcementState(row.original) === "retired" ? null : (
            <Button
              variant="ghost"
              size="sm"
              disabled={isRetiring}
              onClick={() => setConfirming(row.original)}
            >
              {t("notifications.admin.retire.action")}
            </Button>
          ),
      });
    }

    return list;
  }, [t, locale, format, onRetire, isRetiring]);

  return (
    <>
      <AdminDataTable
        rows={rows}
        isLoading={isLoading}
        columns={columns}
        getRowId={(row) => String(row.id)}
        emptyMessage={t("notifications.admin.empty")}
        initialPageSize={25}
      />
      <AlertDialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t("notifications.admin.retire.title")}</AlertDialogTitle>
            {/* Says what actually happens: the row and its read marks stay, the
                announcement simply stops being shown from now on. */}
            <AlertDialogDescription>
              {t("notifications.admin.retire.description")}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t("notifications.admin.retire.cancel")}</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                if (confirming) onRetire?.(confirming);
                setConfirming(null);
              }}
            >
              {t("notifications.admin.retire.action")}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
