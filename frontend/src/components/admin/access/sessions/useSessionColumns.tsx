"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { MonitorSmartphone, UserCog } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { AccessStatusCell } from "@/components/admin/access/AccessStatusCell";
import { columnMeta, createKebabColumn } from "@/components/data-table";
import { useFormatter } from "@/lib/datetime/client";
import type { AdminAuthSession } from "@/types/rbac.types";

import { accountsHref, formatDeviceLabel, formatTimestamp } from "./model";

export function useSessionColumns() {
  const t = useTranslations("adminAccess.common");
  const format = useFormatter();

  return useMemo<ColumnDef<AdminAuthSession>[]>(
    () => [
      {
        id: "user",
        header: t("account"),
        enableSorting: false,
        accessorFn: (row) => row.email ?? row.username ?? t("accountFallback", { id: row.user_id }),
        cell: ({ row }) => (
          <div className="min-w-0">
            <Link
              href={accountsHref(row.original)}
              className="block truncate text-sm font-medium underline-offset-2 hover:underline"
            >
              {row.original.email ??
                (row.original.username
                  ? `@${row.original.username}`
                  : t("accountFallback", { id: row.original.user_id }))}
            </Link>
            {row.original.email && row.original.username ? (
              <p className="truncate text-caption text-muted-foreground">@{row.original.username}</p>
            ) : null}
          </div>
        )
      },
      {
        id: "device",
        header: t("device"),
        enableSorting: false,
        accessorFn: (row) => formatDeviceLabel(row.user_agent, t("unknownDevice")),
        cell: ({ row }) => (
          <span className="flex min-w-0 items-center gap-2">
            <MonitorSmartphone aria-hidden className="size-4 shrink-0 text-muted-foreground" />
            <span className="truncate text-sm">
              {formatDeviceLabel(row.original.user_agent, t("unknownDevice"))}
            </span>
          </span>
        )
      },
      {
        accessorKey: "status",
        header: t("status"),
        meta: columnMeta<AdminAuthSession>({ align: "center" }),
        cell: ({ row }) => <AccessStatusCell status={row.original.status} showActive />
      },
      {
        accessorKey: "login_at",
        header: t("signedIn"),
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.login_at)}
          </span>
        )
      },
      {
        accessorKey: "last_seen_at",
        header: t("lastSeen"),
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.last_seen_at)}
          </span>
        )
      },
      createKebabColumn<AdminAuthSession>(
        (row) => [{ label: t("openAuthAccount"), icon: UserCog, href: accountsHref(row) }],
        {
          rowLabel: (row) =>
            t("sessionRowLabel", {
              account: row.email ?? row.username ?? t("accountFallback", { id: row.user_id })
            })
        }
      )
    ],
    [format, t]
  );
}
