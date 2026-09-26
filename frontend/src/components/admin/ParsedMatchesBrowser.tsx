"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import { AdminDataTable } from "@/components/data-table";
import { ParsedMatchDetail } from "@/components/admin/ParsedMatchDetail";
import { FilterBar } from "@/components/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { StatusPill } from "@/components/kit/StatusPill";
import { type Tone } from "@/components/kit/tone";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam
} from "@/components/admin/tournament-filter";
import { useQueryParams } from "@/hooks/useQueryParams";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import mapService from "@/services/map.service";
import tournamentService from "@/services/tournament.service";
import type { AdminMatchRow, LogProcessingStatus } from "@/types/admin.types";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { mapQueryKeys } from "@/lib/maps/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

const PAGE_SIZE = 25;

const STATUS_TONE: Record<LogProcessingStatus, Tone> = {
  pending: "neutral",
  processing: "info",
  done: "success",
  failed: "danger"
};

/**
 * Every ingestion status a provenance cell can print.
 *
 * `unresolved` is deliberately absent. It is not a status but the absence of an
 * ingestion record, and the endpoint selects it with `unlinked_only` — a
 * different query parameter, which is why it is a chip of its own below.
 */
const LOG_STATUS_OPTIONS: readonly { value: LogProcessingStatus; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "processing", label: "Processing" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" }
];

/**
 * Parsed matches — one row per played map — for one tournament or the whole
 * workspace.
 *
 * Until `mtchlog001` `Encounter.has_logs` was the only admin-visible sign that
 * any of this existed: a boolean on the encounter that could not say which
 * upload produced which map, or whether a map had been parsed at all.
 *
 * Filtering lives in `FilterBar` and row detail in `Inspector`, the
 * two surfaces every admin browser uses, so what an admin narrowed to travels
 * in the URL and the table stays visible beside the map being investigated.
 */
export function ParsedMatchesBrowser({
  tournamentId,
  workspaceId,
  tournamentName
}: Readonly<{
  /** `null` = every tournament in the workspace. */
  tournamentId: number | null;
  workspaceId: number | null;
  /** Names the pinned chip inside a hub; the chip reads `#id` without it. */
  tournamentName?: string | null;
}>) {
  // `id` is the inspector, not a filter: opening a map must not drop the page
  // it sits on.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [] });
  const openId = searchParams?.get("id") ?? null;
  const [pageRows, setPageRows] = useState<AdminMatchRow[]>([]);
  const showTournament = tournamentId == null;

  const chipTournamentId = parseTournamentQueryParam(
    searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null
  );
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  // Map options come from the global catalogue, not from the page of rows: the
  // filter has to offer maps that this page happens not to show.
  const mapsQuery = useQuery({
    queryKey: mapQueryKeys.lookup(),
    queryFn: () => mapService.lookup(),
    staleTime: 5 * 60 * 1000,
    enabled: workspaceId != null
  });

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll(null),
    enabled: workspaceId != null && tournamentId == null
  });

  const defs = useMemo<FilterDef[]>(() => {
    const list: FilterDef[] = [];
    if (tournamentId == null) {
      list.push({
        key: TOURNAMENT_QUERY_PARAM,
        label: "Tournament",
        kind: "single",
        options: (tournamentsQuery.data?.results ?? []).map((entry) => ({
          value: String(entry.id),
          label: entry.name
        }))
      });
    }
    list.push(
      {
        key: "map_id",
        label: "Map",
        kind: "single",
        options: (mapsQuery.data ?? []).map((entry) => ({
          value: String(entry.id),
          label: entry.name
        }))
      },
      {
        key: "log_status",
        label: "Ingestion status",
        kind: "multi",
        options: LOG_STATUS_OPTIONS.map((option) => ({ ...option }))
      },
      // Not a status: this selects maps with no ingestion record at all, which
      // is most of the archive, while `failed` selects the ones whose ingestion
      // actually broke. Merging them would drown the real failures.
      { key: "unlinked_only", label: "Provenance unresolved", kind: "toggle" }
    );
    return list;
  }, [tournamentId, tournamentsQuery.data, mapsQuery.data]);

  const filters = useFilters(defs);
  const mapFilter = String(filters.values.map_id ?? "");
  const statusFilter = Array.isArray(filters.values.log_status)
    ? (filters.values.log_status as LogProcessingStatus[])
    : [];
  const unlinkedOnly = filters.values.unlinked_only === true;

  // The inspector shows a row from the page on screen, so a deep-linked `?id=`
  // the current chips exclude leaves it closed rather than showing detail for a
  // map the list does not contain.
  const openRow = pageRows.find((row) => String(row.id) === openId) ?? null;
  const openIndex = openRow ? pageRows.indexOf(openRow) : -1;

  const columns = useMemo<ColumnDef<AdminMatchRow>[]>(
    () => [
      {
        id: "map",
        header: "Map",
        // The server sorts none of these, so offering a sort control would be a
        // lie the header cannot honour.
        enableSorting: false,
        cell: ({ row }) => (
          <div className="min-w-0 max-w-[20rem]">
            <p className="truncate font-medium text-foreground" title={row.original.map_name}>
              {row.original.map_name}
            </p>
            <p
              className="truncate text-xs text-muted-foreground"
              title={
                showTournament
                  ? `${row.original.tournament_name} · ${row.original.encounter_name}`
                  : row.original.encounter_name
              }
            >
              {showTournament ? `${row.original.tournament_name} · ` : ""}
              {row.original.encounter_name}
            </p>
          </div>
        )
      },
      {
        id: "score",
        header: "Score",
        size: 92,
        enableSorting: false,
        cell: ({ row }) => (
          <span className="font-mono text-sm tabular-nums text-foreground">
            {row.original.home_score} &ndash; {row.original.away_score}
          </span>
        )
      },
      {
        id: "log",
        header: "Log",
        enableSorting: false,
        cell: ({ row }) => (
          <p
            className="max-w-[18rem] truncate font-mono text-xs text-muted-foreground"
            title={row.original.log_name}
          >
            {row.original.log_name}
          </p>
        )
      },
      {
        id: "provenance",
        header: "Provenance",
        size: 148,
        enableSorting: false,
        cell: ({ row }) =>
          row.original.log_record ? (
            <StatusPill tone={STATUS_TONE[row.original.log_record.status]}>
              {row.original.log_record.status}
            </StatusPill>
          ) : (
            // Never "failed": no record is unknown provenance, and the word
            // carries the whole meaning so the state survives greyscale.
            <StatusPill tone="neutral">unresolved</StatusPill>
          )
      }
    ],
    [showTournament]
  );

  if (workspaceId == null) {
    return (
      <EmptyNote>
        Parsed maps are scoped to a workspace. Pick one to see what the log parser produced.
      </EmptyNote>
    );
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        One row per played map, as the log parser produced it. Provenance is the ingestion record the
        map came from.
      </p>

      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <AdminDataTable<AdminMatchRow>
            columns={columns}
            filterKey={filters.filterKey}
            initialPageSize={PAGE_SIZE}
            searchPlaceholder="Search log name, code or team"
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            toolbar={
              <FilterBar
                defs={defs}
                filters={filters}
                pinned={
                  tournamentId != null
                    ? [
                        {
                          key: TOURNAMENT_QUERY_PARAM,
                          label: `Tournament: ${tournamentName ?? `#${tournamentId}`}`
                        }
                      ]
                    : undefined
                }
              />
            }
            emptyMessage={
              unlinkedOnly
                ? "No parsed maps with unresolved provenance."
                : "No parsed maps here yet."
            }
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{row.original.map_name}</p>
                <p className="truncate text-xs text-muted-foreground">
                  {row.original.encounter_name} ·{" "}
                  <span className="font-mono tabular-nums">
                    {row.original.home_score}&ndash;{row.original.away_score}
                  </span>
                </p>
                <p className="truncate font-mono text-xs text-muted-foreground">
                  {row.original.log_record?.status ?? "unresolved"}
                </p>
              </div>
            )}
            queryKey={(page, search, pageSize) => [
              "admin-matches",
              {
                workspaceId,
                tournamentId: scopeTournamentId,
                chip: unlinkedOnly ? "unresolved" : "all",
                page,
                search,
                pageSize,
                filters: { map_id: mapFilter, log_status: statusFilter }
              }
            ]}
            queryFn={async (page, search, pageSize) => {
              const result = await adminService.listAdminMatches({
                workspace_id: workspaceId,
                tournament_id: scopeTournamentId ?? undefined,
                query: search || undefined,
                map_id: mapFilter ? Number(mapFilter) : undefined,
                log_status: statusFilter.length ? statusFilter : undefined,
                ...(unlinkedOnly && { unlinked_only: true }),
                page,
                per_page: pageSize
              });
              // The inspector pages through the rows on screen, and the table
              // owns the fetch, so this is where that page is observed.
              setPageRows(result.results);
              return result;
            }}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow?.map_name ?? ""}
          subtitle={
            openRow ? `${openRow.encounter_name} · ${openRow.tournament_name}` : undefined
          }
          onPrev={
            openIndex > 0 ? () => setParams({ id: String(pageRows[openIndex - 1].id) }) : undefined
          }
          onNext={
            openIndex >= 0 && openIndex < pageRows.length - 1
              ? () => setParams({ id: String(pageRows[openIndex + 1].id) })
              : undefined
          }
        >
          {openRow ? <ParsedMatchDetail row={openRow} workspaceId={workspaceId} /> : null}
        </Inspector>
      </div>
    </div>
  );
}
