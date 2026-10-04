"use client";

import { useMemo } from "react";
import { useTranslations } from "next-intl";
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

import { STREAM_STATUS_TONES } from "./stream-shared";

/**
 * Live Twitch poller tick log: one row per recorded tick, newest first.
 *
 * The health tiles only name the latest tick; this is where an operator sees
 * when polling started failing and whether it recovered. The endpoint returns
 * the whole capped history (200 ticks), so the status filter runs locally.
 */
export function StreamTaskHistory() {
  const t = useTranslations("collectors.streams");
  const tCommon = useTranslations("collectors.common");
  const format = useFormatter();
  const filterDefs = useMemo<FilterDef[]>(
    () => [
      {
        key: "status",
        label: tCommon("status"),
        kind: "single",
        options: (Object.keys(STREAM_STATUS_TONES) as StreamPollStatus[]).map((value) => ({
          value,
          label: t(`status.${value}.label`)
        }))
      }
    ],
    [t, tCommon]
  );
  const filters = useFilters(filterDefs);
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
        header: tCommon("time"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
            {formatDate(format, row.original.ran_at)}
          </span>
        )
      },
      {
        accessorKey: "status",
        header: tCommon("status"),
        // The raw token stays in the cell: the tick log is read next to the
        // service's own logs, which name the same token. The wording is the
        // tooltip.
        cell: ({ row }) => (
          <span title={t(`status.${row.original.status}.label`)}>
            <StatusPill tone={STREAM_STATUS_TONES[row.original.status]}>
              {row.original.status}
            </StatusPill>
          </span>
        )
      },
      {
        accessorKey: "tournaments_updated",
        header: t("history.tournaments"),
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true }),
        cell: ({ row }) => `${row.original.tournaments_updated} / ${row.original.tournaments_active}`
      },
      {
        accessorKey: "channels_polled",
        header: t("history.channels"),
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true })
      },
      {
        accessorKey: "live_channels",
        header: t("history.live"),
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true })
      },
      {
        accessorKey: "ratelimit_remaining",
        header: t("history.rateLimit"),
        meta: columnMeta<StreamPollTick>({ align: "right", numeric: true }),
        cell: ({ row }) => row.original.ratelimit_remaining ?? "—"
      }
    ],
    [format, t, tCommon]
  );

  return (
    <section aria-labelledby="stream-task-history" className="space-y-3">
      <div className="flex items-center gap-2">
        <h2 id="stream-task-history" className="font-semibold leading-none tracking-tight">
          {tCommon("taskHistory")}
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
        toolbar={<FilterBar defs={filterDefs} filters={filters} />}
        getRowId={(row) => row.ran_at}
        emptyMessage={filters.filterKey ? t("history.emptyFiltered") : t("history.empty")}
      />
    </section>
  );
}
