"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { LiveIndicator } from "@/components/admin/LiveIndicator";
import { DataTable, columnMeta } from "@/components/data-table";
import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import adminService from "@/services/admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { RankFetchLogRow } from "@/types/admin.types";

import { StatusBadge, formatDate } from "./rank-shared";

const FILTER_DEFS: FilterDef[] = [
  {
    key: "status",
    label: "Status",
    kind: "single",
    options: ["ok", "private", "not_found", "error", "rate_limited"].map((value) => ({ value, label: value }))
  },
  {
    key: "source",
    label: "Source",
    kind: "single",
    options: ["scheduled", "registration", "manual"].map((value) => ({ value, label: value }))
  }
];

/** The endpoint's own ceiling; the table pages through it client-side. */
const FETCH_LIMIT = 200;

/**
 * Live OverFast worker fetch log.
 *
 * Rows that resolve to a known player link through to that person's page:
 * per-player inspection is People's job now (F14 ·3), so this screen stays
 * about the worker and hands the drill-down off instead of growing a second
 * detail surface below the fold.
 *
 * Status/source filter on the server (the URL holds them), so a rare `error`
 * row is found past the newest 200 rather than only inside them; search and
 * paging run over the fetched rows.
 */
export function RankTaskHistory() {
  const format = useFormatter();
  const router = useRouter();
  const filters = useFilters(FILTER_DEFS);
  const status = String(filters.values.status ?? "");
  const source = String(filters.values.source ?? "");
  // Rows come back scoped to the workspace `apiFetch` injects — key on it so a
  // workspace switch refetches instead of showing the previous tenant's history.
  const workspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);

  const query = useQuery({
    queryKey: adminQueryKeys.rankFetchLog(workspaceId, status || "all", source || "all"),
    queryFn: () =>
      adminService.getRankFetchLog({
        status: status || undefined,
        source: source || undefined,
        limit: FETCH_LIMIT
      }),
    refetchInterval: 3000
  });

  const columns = useMemo<ColumnDef<RankFetchLogRow>[]>(
    () => [
      {
        accessorKey: "created_at",
        header: "Time",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
            {formatDate(format, row.original.created_at)}
          </span>
        )
      },
      {
        accessorKey: "battle_tag",
        header: "Battle tag",
        meta: columnMeta<RankFetchLogRow>({ searchValue: (row) => row.battle_tag }),
        cell: ({ row }) =>
          row.original.user_id != null ? (
            <Link
              href={`/admin/people/${row.original.user_id}`}
              className="font-medium text-primary underline-offset-2 hover:underline"
              onClick={(event) => event.stopPropagation()}
            >
              {row.original.battle_tag}
            </Link>
          ) : (
            <span className="font-medium">{row.original.battle_tag}</span>
          )
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => <StatusBadge status={row.original.status} />
      },
      {
        accessorKey: "source",
        header: "Source",
        cell: ({ row }) => <span className="text-xs text-muted-foreground">{row.original.source}</span>
      },
      {
        accessorKey: "snapshots_written",
        header: "Snapshots",
        meta: columnMeta<RankFetchLogRow>({ align: "right", numeric: true }),
        cell: ({ row }) => row.original.snapshots_written || "—"
      },
      {
        accessorKey: "error",
        header: "Error",
        enableSorting: false,
        cell: ({ row }) =>
          row.original.error ? (
            <span className="block max-w-64 truncate text-xs text-danger" title={row.original.error}>
              {row.original.error}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">—</span>
          )
      }
    ],
    [format]
  );

  return (
    <section aria-labelledby="rank-task-history" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 id="rank-task-history" className="font-semibold leading-none tracking-tight">
          Task history
        </h2>
        <LiveIndicator />
      </div>
      <DataTable<RankFetchLogRow>
        rows={query.data ?? []}
        isLoading={query.isLoading}
        columns={columns}
        initialPageSize={20}
        pageSizeOptions={[20, 50, 100, 200]}
        searchPlaceholder="Search battle tags…"
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={FILTER_DEFS} filters={filters} />}
        getRowId={(row) => String(row.id)}
        emptyMessage={
          filters.filterKey
            ? "No fetch task matches these filters."
            : "No fetch tasks recorded yet. The worker logs a row here each time it queries OverFast — resume collection or collect a single player to see activity."
        }
        onRowClick={(row) => {
          if (row.original.user_id != null) router.push(`/admin/people/${row.original.user_id}`);
        }}
      />
    </section>
  );
}
