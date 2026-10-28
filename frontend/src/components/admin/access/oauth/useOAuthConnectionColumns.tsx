"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
import type { ColumnDef } from "@tanstack/react-table";
import { Clock, Trash2, UserCog } from "lucide-react";

import { columnMeta, createKebabColumn } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { ProviderMark } from "@/components/admin/OAuthProviderMark";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { useFormatter } from "@/lib/datetime/client";
import type { OAuthConnectionAdmin, OAuthProvider } from "@/types/rbac.types";

import { accountsHref, isTokenExpired } from "./model";

/** The connection row: the provider account, the auth account it signs in as, and its token. */
export function useOAuthConnectionColumns({
  canDeleteConnections,
  providerLabel,
  onDelete
}: Readonly<{
  canDeleteConnections: boolean;
  /** Stable identity required, like `onDelete`: the kebab column closes over both. */
  providerLabel: (provider: OAuthProvider) => string;
  onDelete: (connection: OAuthConnectionAdmin) => void;
}>): ColumnDef<OAuthConnectionAdmin>[] {
  const t = useTranslations("adminAccess.common");
  const format = useFormatter();
  return useMemo<ColumnDef<OAuthConnectionAdmin>[]>(
    () => [
      {
        accessorKey: "id",
        header: t("id"),
        size: 60,
        cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>
      },
      {
        accessorKey: "provider",
        header: t("provider"),
        cell: ({ row }) => <ProviderMark provider={row.original.provider} />
      },
      {
        id: "provider_user",
        header: t("providerAccount"),
        enableSorting: false,
        cell: ({ row }) => {
          const connection = row.original;
          return (
            <div className="flex min-w-0 items-center gap-3">
              <Avatar className="size-8">
                <AvatarImage src={connection.avatar_url ?? undefined} alt={connection.username} />
                <AvatarFallback>
                  {connection.username.slice(0, 2).toUpperCase()}
                </AvatarFallback>
              </Avatar>
              <div className="min-w-0">
                <p className="truncate text-sm font-medium">
                  {connection.display_name ?? connection.username}
                </p>
                <p className="truncate text-xs text-muted-foreground">
                  {connection.username}
                  {connection.email ? ` \u00B7 ${connection.email}` : ""}
                </p>
              </div>
            </div>
          );
        }
      },
      {
        id: "auth_user",
        header: t("authorization"),
        enableSorting: false,
        cell: ({ row }) => (
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{row.original.auth_user_username}</p>
            <p className="truncate text-xs text-muted-foreground">
              {row.original.auth_user_email}
            </p>
          </div>
        )
      },
      {
        id: "token_status",
        header: t("token"),
        enableSorting: false,
        meta: columnMeta({ align: "center" }),
        cell: ({ row }) =>
          isTokenExpired(row.original.token_expires_at) ? (
            <StatusIcon icon={Clock} label={t("expired")} variant="destructive" />
          ) : null
      },
      {
        accessorKey: "created_at",
        header: t("connected"),
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-muted-foreground">
            {format.dateTime(new Date(row.original.created_at), {
              year: "numeric",
              month: "short",
              day: "numeric"
            })}
          </span>
        )
      },
      createKebabColumn<OAuthConnectionAdmin>(
        (row) => [
          { label: t("openAuthAccount"), icon: UserCog, href: accountsHref(row) },
          {
            label: t("removeConnection"),
            icon: Trash2,
            destructive: true,
            hidden: !canDeleteConnections,
            onSelect: () => onDelete(row)
          }
        ],
        {
          rowLabel: (row) =>
            t("oauthRowLabel", { provider: providerLabel(row.provider), account: row.username })
        }
      )
    ],
    [canDeleteConnections, format, onDelete, providerLabel, t]
  );
}
