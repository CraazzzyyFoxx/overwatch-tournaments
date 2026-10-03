"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { LiveIndicator } from "@/components/admin/LiveIndicator";
import { DataTable, columnMeta } from "@/components/data-table";
import { FilterBar } from "@/components/kit/FilterBar";
import { formatDate } from "@/components/kit/format-time";
import { StatusPill } from "@/components/kit/StatusPill";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import adminService from "@/services/admin.service";
import type { StreamPollStatus, StreamPollTick } from "@/types/admin.types";

import { STREAM_STATUS_META } from "./stream-shared";

const FILTER_DEFS: FilterDef[] = [
  {
    key: "status",
    label: "Status",
    kind: "single",
    options: (Object.keys(STREAM_STATUS_META) as StreamPollStatus[]).map((value) => ({
      value,
      label: value
    }))
  }
];

/**
 * Live Twitch poller tick log: one row per recorded tick, newest first.
 *
 * The health tiles only name the latest tick; this is where an operator sees
 * when polling started failing and whether it recovered. The endpoint returns
 * the whole capped history (200 ticks), so the status filter runs locally.
 */
export function StreamTaskHistory() {
  const format = useFormatter();
  const filters = useFilters(FILTER_DEFS);
  const status = String(filters.values.status ?? "");

  // No workspace in the key: one poller, one Redis list. Ticks are at least 30s
  // apart, so polling harder only re-renders the same rows.
  const query = useQuery({
    queryKey: adminQueryKeys.streamsTicks(),
    queryFn: () => adminService.getStreamPollTicks(),
    refetchInterval: 30_000
  });
  const rows = (query.data ?? []).filter((tick) => !status || tick.status === status);

  const columns = useMemo<ColumnDef<StreamPollTick>[]>(
    () => [
      {
        accessorKey: "ran_at",
        header: "Time",
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
            {formatDate(format, row.original.ran_at)}
          </span>
        )
      },
      {
        accessorKey: "status",
        header: "Status",
        cell: ({ row }) => (
          <span title={STREAM_STATUS_META[row.original.status].label}>
            <StatusPill tone={STREAM_STATUS_META[row.original.status].tone}>{row.original.status}</StatusPill>
          </span>
        )
      },
      {
        accessorKey: "tournaments_updated",
        header: "Tournaments",
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true }),
        cell: ({ row }) => `${row.original.tournaments_updated} / ${row.original.tournaments_active}`
      },
      {
        accessorKey: "channels_polled",
        header: "Channels",
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true })
      },
      {
        accessorKey: "live_channels",
        header: "Live",
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true })
      },
      {
        accessorKey: "ratelimit_remaining",
        header: "Rate limit left",
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true }),
        cell: ({ row }) => row.original.ratelimit_remaining ?? "—"
      }
    ],
    [format]
  );

  return (
    <section aria-labelledby="stream-task-history" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 id="stream-task-history" className="font-semibold leading-none tracking-tight">
          Task history
        </h2>
        <LiveIndicator />
      </div>
      <DataTable<StreamPollTick>
        rows={rows}
        isLoading={query.isLoading}
        columns={columns}
        initialPageSize={20}
        pageSizeOptions={[20, 50, 100, 200]}
        filterKey={filters.filterKey}
        toolbar={<FilterBar defs={FILTER_DEFS} filters={filters} />}
        getRowId={(row) => row.ran_at}
        emptyMessage={
          filters.filterKey
            ? "No tick matches this status."
            : "No ticks recorded yet. The poller logs a row here on every tick once polling is on and an interval has elapsed."
        }
      />
    </section>
  );
}
