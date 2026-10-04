"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { LiveIndicator } from "@/components/admin/LiveIndicator";
import { DataTable, columnMeta } from "@/components/data-table";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { SocialIcon } from "@/components/social/SocialIcon";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { SubscriptionCheckLogRow } from "@/types/admin.types";

import {
  PROVIDER_LABELS,
  STATE_ORDER,
  SOURCE_ORDER,
  StateBadge,
  formatDate,
  useSubscriptionLabels
} from "./subscription-shared";

/** The endpoint's own ceiling; the table pages through it client-side. */
const FETCH_LIMIT = 200;

/**
 * Live subscription check history — one row per real provider call.
 *
 * This is the view the subscription domain had no data for: `entitlement` is
 * overwritten in place on every check, so before `check_log` existed there was
 * no way to see that a player flapped, when a provider went down, or why a
 * registration was refused. Rows that resolve to a player link through to that
 * person's page (F14 ·3) rather than opening a detail panel here.
 *
 * State/provider/trigger filter on the server (the URL holds them), so a rare
 * `error` row is found past the newest 200; search and paging run over the
 * fetched rows.
 */
export function SubscriptionTaskHistory() {
  const t = useTranslations("collectors.subscriptions");
  const tCommon = useTranslations("collectors.common");
  const format = useFormatter();
  const router = useRouter();
  const labels = useSubscriptionLabels();
  const filterDefs = useMemo<FilterDef[]>(
    () => [
      {
        key: "state",
        label: t("history.state"),
        kind: "single",
        options: STATE_ORDER.map((value) => ({ value, label: labels.state[value] }))
      },
      {
        key: "provider",
        label: t("history.provider"),
        kind: "single",
        options: Object.entries(PROVIDER_LABELS).map(([value, label]) => ({ value, label }))
      },
      {
        key: "source",
        label: t("history.trigger"),
        kind: "single",
        options: SOURCE_ORDER.map((value) => ({ value, label: labels.source[value] }))
      }
    ],
    [t, labels]
  );
  const filters = useFilters(filterDefs);
  const state = String(filters.values.state ?? "");
  const source = String(filters.values.source ?? "");
  const provider = String(filters.values.provider ?? "");
  // Rows come back scoped to the workspace `apiFetch` injects — key on it so a
  // workspace switch refetches instead of showing the previous tenant's history.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const query = useQuery({
    queryKey: adminQueryKeys.subscriptionsCheckLog(
      workspaceId,
      state || "all",
      source || "all",
      provider || "all"
    ),
    queryFn: () =>
      adminService.getSubscriptionCheckLog({
        state: state || undefined,
        source: source || undefined,
        provider: provider || undefined,
        limit: FETCH_LIMIT
      }),
    refetchInterval: 3000
  });

  const columns = useMemo<ColumnDef<SubscriptionCheckLogRow>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: tCommon("time"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
            {formatDate(format, row.original.created_at)}
          </span>
        )
      },
      {
        id: "player",
        accessorFn: (row) => row.user_name ?? `auth #${row.auth_user_id ?? "?"}`,
        header: t("history.player"),
        meta: columnMeta<SubscriptionCheckLogRow>({
          searchValue: (row) => row.user_name ?? `auth #${row.auth_user_id ?? "?"}`
        }),
        cell: ({ row, getValue }) =>
          row.original.user_id != null ? (
            <Link
              href={`/admin/people/${row.original.user_id}`}
              className="font-medium text-primary underline-offset-2 hover:underline"
              onClick={(event) => event.stopPropagation()}
            >
              {String(getValue())}
            </Link>
          ) : (
            <span className="font-medium">{String(getValue())}</span>
          )
      },
      {
        accessorKey: "provider",
        header: t("history.provider"),
        cell: ({ row }) => (
          <span className="flex items-center gap-2 text-sm">
            <SocialIcon provider={row.original.provider} size={14} decorative />
            <span>{PROVIDER_LABELS[row.original.provider] ?? row.original.provider}</span>
          </span>
        )
      },
      {
        accessorKey: "state",
        header: t("history.state"),
        cell: ({ row }) => <StateBadge state={row.original.state} />
      },
      {
        id: "tier",
        header: t("history.tier"),
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-xs tabular-nums text-muted-foreground">
            {row.original.tier_label ??
              (row.original.tier_rank != null
                ? t("history.tierRank", { rank: row.original.tier_rank })
                : "—")}
          </span>
        )
      },
      {
        accessorKey: "source",
        header: t("history.trigger"),
        cell: ({ row }) => (
          <span className="text-xs text-muted-foreground" title={row.original.mechanism ?? undefined}>
            {labels.source[row.original.source] ?? row.original.source}
          </span>
        )
      },
      {
        id: "reason",
        header: t("history.reason"),
        enableSorting: false,
        cell: ({ row }) => {
          const { error, reason } = row.original;
          const text = error ?? (reason ? labels.reason(reason) : null);
          return (
            <span
              className={cn(
                "block max-w-64 truncate text-xs",
                error ? "text-danger" : "text-muted-foreground"
              )}
              title={error ?? reason ?? undefined}
            >
              {text ?? "—"}
            </span>
          );
        }
      }
    ],
    [format, t, tCommon, labels]
  );

  return (
    <section aria-labelledby="subscription-check-history" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 id="subscription-check-history" className="font-semibold leading-none tracking-tight">
          {t("history.title")}
        </h2>
        <LiveIndicator />
      </div>
      <DataTable<SubscriptionCheckLogRow>
        rows={query.data ?? []}
        isLoading={query.isLoading}
        columns={columns}
        initialPageSize={20}
        pageSizeOptions={[20, 50, 100, 200]}
        searchPlaceholder={t("history.searchPlaceholder")}
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        getRowId={(row) => String(row.id)}
        emptyMessage={filters.filterKey ? t("history.emptyFiltered") : t("history.empty")}
        onRowClick={(row) => {
          if (row.original.user_id != null) router.push(`/admin/people/${row.original.user_id}`);
        }}
      />
    </section>
  );
}
