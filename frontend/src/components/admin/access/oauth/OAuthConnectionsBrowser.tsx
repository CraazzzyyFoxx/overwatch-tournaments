"use client";

import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { DataTable } from "@/components/data-table";
import { PROVIDER_META } from "@/components/admin/OAuthProviderMark";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { useFilters } from "@/components/kit/useFilters";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { notify } from "@/lib/notify";
import { cn } from "@/lib/utils";
import { rbacService } from "@/services/rbac.service";
import type { OAuthConnectionAdmin, OAuthProvider } from "@/types/rbac.types";
import { accessQueryKeys } from "@/lib/access/query-keys";

import { useOAuthConnectionFilterDefs } from "./filters";
import { accountsHref, isTokenExpired } from "./model";
import { OAuthConnectionInspectorPanel } from "./OAuthConnectionInspectorPanel";
import { useOAuthConnectionColumns } from "./useOAuthConnectionColumns";

const PAGE_SIZE = 20;

/**
 * OAuth connections (T2, F15): which provider account signs in as which auth
 * account.
 *
 * The provider `<Select>` in the toolbar is now a URL chip, so "every Discord
 * connection" is a link rather than a sequence of clicks, and the detail a
 * support question actually needs (provider id, token expiry, the auth
 * account) moved from the row into the inspector.
 */
export function OAuthConnectionsBrowser() {
  const t = useTranslations("adminAccess.common");
  const to = useTranslations("adminAccess.oauthUi");
  const queryClient = useQueryClient();
  const router = useRouter();
  const { hasPermission } = usePermissions();
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;
  const providerLabel = useCallback(
    (provider: OAuthProvider): string => t(PROVIDER_META[provider]?.labelKey ?? "provider"),
    [t]
  );

  const canDeleteConnections = hasPermission("auth_user.update");
  const [pageRows, setPageRows] = useState<OAuthConnectionAdmin[]>([]);
  const [pendingDelete, setPendingDelete] = useState<OAuthConnectionAdmin | null>(null);

  const defs = useOAuthConnectionFilterDefs(providerLabel);
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
      notify.success(to("removed"));
    },
    onError: (error) => notify.apiError(error)
  });

  const columns = useOAuthConnectionColumns({
    canDeleteConnections,
    providerLabel,
    onDelete: setPendingDelete
  });

  return (
    <div className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}>
      <div className="min-w-0">
        <DataTable<OAuthConnectionAdmin>
          columns={columns}
          initialPageSize={PAGE_SIZE}
          pageSizeOptions={[10, 20, 50, 100]}
          searchPlaceholder={to("search")}
          filterKey={filters.filterKey}
          inspectorId={openId}
          getRowId={(row) => String(row.id)}
          toolbar={<FilterBar defs={defs} filters={filters} />}
          emptyMessage={to("noMatches")}
          onRowClick={(row) => setParams({ id: String(row.original.id) })}
          onRowDoubleClick={(row) => router.push(accountsHref(row.original))}
          renderMobileCard={(row) => (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {row.original.display_name ?? row.original.username}
              </p>
              <p className="truncate text-xs text-muted-foreground">
                {providerLabel(row.original.provider)} · {row.original.auth_user_username}
              </p>
              {isTokenExpired(row.original.token_expires_at) ? (
                <p className="truncate text-xs text-warning">{to("tokenExpired")}</p>
              ) : null}
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
          queryFn={(page, search, pageSize, sortField, sortDir) =>
            rbacService.listOAuthConnections({
              page,
              per_page: pageSize,
              sort: sortField ?? undefined,
              order: sortDir,
              search: search || undefined,
              provider: providerFilter || undefined
            })
          }
          onPageRowsChange={setPageRows}
        />
      </div>

      <Inspector
        openId={openRow ? openId : null}
        onClose={() => setParams({ id: null })}
        title={openRow ? (openRow.display_name ?? openRow.username) : ""}
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
        {openRow ? <OAuthConnectionInspectorPanel connection={openRow} /> : null}
      </Inspector>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open) setPendingDelete(null);
        }}
        pending={deleteMutation.isPending}
        intent={{
          title: to("removeTitle"),
          description: pendingDelete
            ? to("removeDescription", {
                account: pendingDelete.display_name ?? pendingDelete.username,
                authAccount:
                  pendingDelete.auth_user_username ??
                  t("accountFallback", { id: pendingDelete.auth_user_id }),
                provider: providerLabel(pendingDelete.provider)
              })
            : "",
          confirmLabel: t("removeConnection"),
          tone: "danger"
        }}
        onConfirm={() => {
          if (pendingDelete) deleteMutation.mutate(pendingDelete.id);
        }}
      />
    </div>
  );
}
