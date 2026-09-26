"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import type { ColumnDef } from "@tanstack/react-table";
import { CheckCircle, Clock, Trash2, UserCog } from "lucide-react";
import { useFormatter } from "@/lib/datetime/client";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { AdminDataTable, adminColumnMeta, createKebabColumn } from "@/components/data-table";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { PROVIDER_META, ProviderBadge } from "@/components/admin/OAuthProviderBadge";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { EYEBROW_CLASS } from "@/components/kit/tone";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import type { OAuthConnectionAdmin, OAuthProvider } from "@/types/rbac.types";
import { accessQueryKeys } from "@/lib/access/query-keys";

const PAGE_SIZE = 20;

function providerLabel(provider: OAuthProvider): string {
  return PROVIDER_META[provider]?.label ?? provider;
}

function isTokenExpired(expiresAt: string | null | undefined): boolean {
  if (!expiresAt) return false;
  return new Date(expiresAt) < new Date();
}

function accountsHref(connection: OAuthConnectionAdmin): string {
  const needle = connection.auth_user_username ?? connection.auth_user_email ?? "";
  return `/admin/access/accounts?search=${encodeURIComponent(needle)}`;
}

function Field({ label, children }: Readonly<{ label: string; children: React.ReactNode }>) {
  return (
    <div className="min-w-0">
      <p className={EYEBROW_CLASS}>{label}</p>
      <div className="mt-0.5 break-words text-sm">{children}</div>
    </div>
  );
}

/**
 * OAuth connections (T2, F15): which provider account signs in as which auth
 * account.
 *
 * The provider `<Select>` in the toolbar is now a URL chip, so "every Discord
 * connection whose token expired" is a link rather than a sequence of clicks,
 * and the detail a support question actually needs — provider id, token
 * expiry, the auth account — moved from the row into the inspector.
 */
export default function OAuthConnectionsAdminPage() {
  const format = useFormatter();
  const queryClient = useQueryClient();
  const { hasPermission } = usePermissions();
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;

  const canDeleteConnections = hasPermission("auth_user.update");
  const [pageRows, setPageRows] = useState<OAuthConnectionAdmin[]>([]);
  const [pendingDelete, setPendingDelete] = useState<OAuthConnectionAdmin | null>(null);

  const defs = useMemo<FilterDef[]>(
    () => [
      {
        key: "provider",
        label: "Provider",
        kind: "single",
        options: (Object.keys(PROVIDER_META) as OAuthProvider[]).map((provider) => ({
          value: provider,
          label: providerLabel(provider)
        }))
      }
    ],
    []
  );
  const filters = useFilters(defs);
  const providerFilter = String(filters.values.provider ?? "");

  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const deleteMutation = useMutation({
    mutationFn: (connectionId: number) => rbacService.deleteOAuthConnection(connectionId),
    onSuccess: async () => {
      const removed = pendingDelete;
      await queryClient.invalidateQueries({ queryKey: accessQueryKeys.oauthConnections() });
      setPendingDelete(null);
      if (removed && String(removed.id) === openId) setParams({ id: null });
      notify.success("OAuth connection removed");
    },
    onError: (error) => notify.apiError(error)
  });

  const columns = useMemo<ColumnDef<OAuthConnectionAdmin>[]>(
    () => [
      {
        accessorKey: "id",
        header: "ID",
        size: 60,
        cell: ({ row }) => <span className="tabular-nums">{row.original.id}</span>
      },
      {
        accessorKey: "provider",
        header: "Provider",
        cell: ({ row }) => <ProviderBadge provider={row.original.provider} />
      },
      {
        id: "provider_user",
        header: "Provider account",
        enableSorting: false,
        cell: ({ row }) => {
          const connection = row.original;
          return (
            <div className="flex min-w-0 items-center gap-3">
              <Avatar className="size-8">
                <AvatarImage src={connection.avatar_url ?? undefined} alt={connection.username} />
                <AvatarFallback className="text-xs">
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
        header: "Auth account",
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
        header: "Token",
        enableSorting: false,
        meta: adminColumnMeta({ align: "center" }),
        cell: ({ row }) => {
          const expiresAt = row.original.token_expires_at;
          if (!expiresAt) {
            return <span className="text-xs text-muted-foreground">No token</span>;
          }
          const expired = isTokenExpired(expiresAt);
          return expired ? (
            <StatusIcon icon={Clock} label="Expired" variant="destructive" />
          ) : (
            <StatusIcon icon={CheckCircle} label="Active" variant="success" />
          );
        }
      },
      {
        accessorKey: "created_at",
        header: "Connected",
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
          { label: "Open auth account", icon: UserCog, href: accountsHref(row) },
          {
            label: "Remove connection",
            icon: Trash2,
            destructive: true,
            hidden: !canDeleteConnections,
            onSelect: () => setPendingDelete(row)
          }
        ],
        {
          rowLabel: (row) => `${providerLabel(row.provider)} connection for ${row.username}`
        }
      )
    ],
    [canDeleteConnections, format]
  );

  return (
    <div className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        <AdminDataTable<OAuthConnectionAdmin>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          pageSizeOptions={[10, 20, 50, 100]}
          searchPlaceholder="Search by username, email, or provider ID…"
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={<FilterBar defs={defs} filters={filters} />}
          emptyMessage="No OAuth connection matches. Clear the provider chip to see every connection."
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {row.original.display_name ?? row.original.username}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {providerLabel(row.original.provider)} · {row.original.auth_user_username}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {row.original.token_expires_at
                  ? isTokenExpired(row.original.token_expires_at)
                    ? "Token expired"
                    : "Token active"
                  : "No token"}
              </p>
            </div>
          )}
          queryKey={(page, search, pageSize, sortField, sortDir) => [
            "access-admin",
            "oauth-connections",
            page,
            search,
            pageSize,
            sortField,
            sortDir,
            providerFilter
          ]}
          queryFn={async (page, search, pageSize, sortField, sortDir) => {
            const result = await rbacService.listOAuthConnections({
              page,
              per_page: pageSize,
              sort: sortField ?? undefined,
              order: sortDir,
              search: search || undefined,
              provider: providerFilter || undefined
            });
            setPageRows(result.results);
            return result;
          }}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? (openRow.display_name ?? openRow.username) : ""}
        subtitle={openRow ? providerLabel(openRow.provider) : undefined}
        openHref={openRow ? accountsHref(openRow) : undefined}
        onPrev={
          openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
        }
        onNext={
          openIndex >= 0 && openIndex < pageRows.length - 1
            ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
            : undefined
        }
      >
        {openRow ? (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Provider">
              <ProviderBadge provider={openRow.provider} />
            </Field>
            <Field label="Provider id">
              <span className="font-mono tabular-nums">{openRow.provider_user_id}</span>
            </Field>
            <Field label="Provider username">{openRow.username}</Field>
            <Field label="Provider email">{openRow.email ?? "Not shared"}</Field>
            <Field label="Auth account">
              <Link
                href={accountsHref(openRow)}
                className="text-primary hover:underline"
              >
                {openRow.auth_user_username ?? `#${openRow.auth_user_id}`}
              </Link>
            </Field>
            <Field label="Auth email">{openRow.auth_user_email ?? "Unavailable"}</Field>
            <Field label="Connected">
              <span className="tabular-nums">{openRow.created_at.slice(0, 10)}</span>
            </Field>
            <Field label="Token">
              {openRow.token_expires_at
                ? `${isTokenExpired(openRow.token_expires_at) ? "Expired" : "Valid until"} ${openRow.token_expires_at.slice(0, 10)}`
                : "No stored token"}
            </Field>
          </div>
        ) : null}
      </Inspector>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: "Remove OAuth connection",
          description: pendingDelete
            ? `This detaches ${pendingDelete.display_name ?? pendingDelete.username} from auth account ${pendingDelete.auth_user_username ?? `#${pendingDelete.auth_user_id}`}. That account can no longer sign in with ${providerLabel(pendingDelete.provider)} until it reconnects the provider itself.`
            : "",
          confirmLabel: "Remove connection",
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
