"use client";

import { useMemo } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Gauge, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { AccessStatusCell } from "@/components/admin/access/AccessStatusCell";
import { columnMeta, createKebabColumn } from "@craazzzyyfoxx/admin-kit/data-table";
import { InlineEditText } from "@/components/kit/InlineEditText";
import { Tooltip, TooltipContent, TooltipTrigger } from "@craazzzyyfoxx/admin-kit/ui/tooltip";
import { useFormatter } from "@/lib/datetime/client";
import { notify } from "@/lib/notify";
import type { AccountApiKey } from "@/types/auth.types";

import { FULL_ACCESS_SCOPE, formatTimestamp, getApiKeyStatus } from "./model";

/**
 * What a key may do, said once: a superuser key passes every check, `admin.*`
 * is full access, none is inert; otherwise a count with the list in a tooltip
 * (the `TooltipProvider` is mounted by the admin layout).
 */
function ScopesCell({ apiKey }: Readonly<{ apiKey: AccountApiKey }>) {
  const t = useTranslations("adminAccess.common");
  const ta = useTranslations("adminAccess.apiKeysUi");
  const { scopes } = apiKey;
  if (apiKey.is_superuser) return <span className="text-sm text-danger">{t("superuser")}</span>;
  if (scopes.includes(FULL_ACCESS_SCOPE)) {
    return <span className="text-sm text-danger">{ta("fullAccess")}</span>;
  }
  if (scopes.length === 0) return <span className="text-sm text-danger">{ta("noScopes")}</span>;
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="text-sm tabular-nums">{ta("scopeCount", { count: scopes.length })}</span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-mono text-xs leading-relaxed">{scopes.join(", ")}</p>
      </TooltipContent>
    </Tooltip>
  );
}

/**
 * `onRename` is the rename mutation's `mutateAsync`, so the inline editor can
 * keep its draft when the write fails. `onEditQuota` and `onRevoke` open the
 * browser's dialogs; all three keep a stable identity, so the columns are
 * rebuilt only when the locale or the formatter changes.
 */
export function useApiKeyColumns({
  onRename,
  onEditQuota,
  onRevoke
}: Readonly<{
  onRename: (input: { id: number; name: string }, options: { onSuccess: () => void }) => Promise<unknown>;
  onEditQuota: (apiKey: AccountApiKey) => void;
  onRevoke: (apiKey: AccountApiKey) => void;
}>) {
  const t = useTranslations("adminAccess.common");
  const ta = useTranslations("adminAccess.apiKeysUi");
  const tQuota = useTranslations("quota");
  const format = useFormatter();

  return useMemo<ColumnDef<AccountApiKey>[]>(
    () => [
      {
        accessorKey: "name",
        header: t("name"),
        cell: ({ row }) => {
          const apiKey = row.original;
          return (
            <div className="min-w-0">
              <InlineEditText
                value={apiKey.name}
                label={ta("nameLabel", { name: apiKey.name })}
                canEdit={getApiKeyStatus(apiKey) === "active"}
                textClassName="text-sm font-medium"
                onSave={(next) =>
                  onRename(
                    { id: apiKey.id, name: next },
                    { onSuccess: () => notify.success(ta("renamed")) }
                  )
                }
              />
              <p className="truncate font-mono text-xs text-muted-foreground">
                owt_sk_{apiKey.public_id}_…
              </p>
            </div>
          );
        }
      },
      {
        id: "owner",
        header: t("owner"),
        enableSorting: false,
        cell: ({ row }) => (
          <span className="truncate text-sm">{row.original.owner_username}</span>
        )
      },
      {
        id: "status",
        header: t("status"),
        enableSorting: false,
        meta: columnMeta<AccountApiKey>({ align: "center" }),
        cell: ({ row }) => (
          <AccessStatusCell status={getApiKeyStatus(row.original)} showActive={false} />
        )
      },
      {
        id: "scopes",
        header: t("scopes"),
        enableSorting: false,
        cell: ({ row }) => <ScopesCell apiKey={row.original} />
      },
      {
        accessorKey: "created_at",
        header: t("created"),
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.created_at, t("never"))}
          </span>
        )
      },
      {
        accessorKey: "last_used_at",
        header: t("lastUsed"),
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.last_used_at, t("never"))}
          </span>
        )
      },
      {
        accessorKey: "expires_at",
        header: t("expires"),
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {formatTimestamp(format, row.original.expires_at, t("never"))}
          </span>
        )
      },
      createKebabColumn<AccountApiKey>(
        (row) => [
          {
            label: tQuota("apiKey.menuItem"),
            icon: Gauge,
            onSelect: () => onEditQuota(row)
          },
          {
            label: t("revokeKey"),
            icon: Trash2,
            destructive: true,
            hidden: getApiKeyStatus(row) !== "active",
            onSelect: () => onRevoke(row)
          }
        ],
        { rowLabel: (row) => ta("rowLabel", { name: row.name }) }
      )
    ],
    [format, onEditQuota, onRename, onRevoke, tQuota, t, ta]
  );
}
