"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { FileQuestion } from "lucide-react";

import { DataTable } from "@craazzzyyfoxx/admin-kit/data-table";
import { LogStatusPill, ParsedMatchDetail } from "@/components/admin/ParsedMatchDetail";
import { StatusIcon } from "@/components/admin/StatusIcon";
import { FilterBar } from "@craazzzyyfoxx/admin-kit/kit/FilterBar";
import { Inspector } from "@/components/kit/Inspector";
import { useFilters, type FilterDef } from "@craazzzyyfoxx/admin-kit/kit/useFilters";
import { gameFilterDefs } from "@/components/admin/game-filter";
import {
  TOURNAMENT_QUERY_PARAM,
  parseTournamentQueryParam,
  strandedTournamentParams,
  tournamentOptions
} from "@/components/admin/tournament-filter";
import { PageStateCard } from "@/components/ui/page-state-card";
import { RowGameLabel, gameColumn } from "@/components/workspace/game-column";
import { useQueryParams } from "@/hooks/useQueryParams";
import { ALL_DISCIPLINES } from "@/lib/site/discipline-scope";
import { cn } from "@/lib/utils";
import adminService from "@/services/admin.service";
import { scoreLine } from "@/lib/encounter/detail";
import { mapWithModeName } from "@/lib/catalog/mode";
import tournamentService from "@/services/tournament.service";
import type { AdminMatchRow, LogProcessingStatus } from "@/types/admin.types";
import type { DisciplineDescriptor } from "@/types/discipline.types";
import { useCatalogEntities } from "@/hooks/useCatalogEntities";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

const PAGE_SIZE = 25;

/**
 * Every ingestion status a provenance cell can print.
 *
 * A missing raw log is not an ingestion status. The endpoint selects matches
 * without a linked job through the separate `unlinked_only` filter.
 */
const LOG_STATUS_OPTIONS: readonly { value: LogProcessingStatus; label: LogProcessingStatus }[] = [
  { value: "pending", label: "pending" },
  { value: "processing", label: "processing" },
  { value: "awaiting_link", label: "awaiting_link" },
  { value: "done", label: "done" },
  { value: "failed", label: "failed" }
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
  discipline,
  workspaceId,
  games
}: Readonly<{
  /** `null` = every tournament in the workspace. */
  tournamentId: number | null;
  /**
   * The pinned tournament's game, else the workspace view's Game chip (`?discipline=`, spec §6.9): a code filters the
   * list on the server; `null` = every game, with a "Game" column.
   */
  discipline: string | null;
  workspaceId: number | null;
  /** The community's games, for the Game chip; absent in a hub. */
  games?: readonly DisciplineDescriptor[];
}>) {
  const t = useTranslations("adminMatches.parsed");
  const tGame = useTranslations("common.discipline");
  // `id` is the inspector, not a filter: opening a map must not drop the page
  // it sits on.
  const { searchParams, setParams } = useQueryParams({ resetOnChange: [], shallow: true });
  const openId = searchParams?.get("id") ?? null;
  const [pageRows, setPageRows] = useState<AdminMatchRow[]>([]);
  const showTournament = tournamentId == null;

  // The tournament chip works under every game; a pinned tournament keeps working.
  const chipTournamentId = parseTournamentQueryParam(searchParams?.get(TOURNAMENT_QUERY_PARAM) ?? null);
  const scopeTournamentId = tournamentId ?? chipTournamentId;

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.adminList(workspaceId, ALL_DISCIPLINES),
    queryFn: () => tournamentService.getAll(workspaceId),
    enabled: workspaceId != null && tournamentId == null
  });
  const chipTournamentGame = tournamentsQuery.data?.results.find(
    (entry) => entry.id === chipTournamentId
  )?.discipline;
  // Maps are one game's catalogue: the filtered game's, else the chosen tournament's (spec §6.2).
  const mapGame = discipline ?? chipTournamentGame ?? null;

  // Map options come from the game's catalogue, not from the page of rows: the
  // filter has to offer maps that this page happens not to show.
  const mapsQuery = useCatalogEntities(mapGame, "map", { enabled: workspaceId != null });

  const defs = useMemo<FilterDef[]>(() => {
    // A game pick always drops the map (another game's catalogue), and a tournament of another game.
    const list = gameFilterDefs(games, tGame("column"), (next) => [
      "map_id",
      ...strandedTournamentParams(chipTournamentGame, next)
    ]);
    if (tournamentId == null) {
      list.push({
        key: TOURNAMENT_QUERY_PARAM,
        label: t("tournament"),
        kind: "single",
        options: tournamentOptions(tournamentsQuery.data?.results ?? [], discipline),
        // With no game filtered the map catalogue is the tournament's, so another tournament strands the map.
        resets: discipline === null ? () => ["map_id"] : undefined
      });
    }
    // Without a game (filtered or the tournament's) there is no catalogue to pick a map from.
    if (mapGame !== null) {
      list.push({
        key: "map_id",
        label: t("map"),
        kind: "single",
        options: (mapsQuery.data ?? []).map((entry) => ({
          value: String(entry.id),
          label: entry.name
        }))
      });
    }
    list.push(
      {
        key: "log_status",
        label: t("ingestionStatus"),
        kind: "multi",
        options: LOG_STATUS_OPTIONS.map((option) => ({
          ...option,
          label: t(option.label)
        }))
      },
      // No linked raw log, not an ingestion failure.
      { key: "unlinked_only", label: t("noRawLog"), kind: "toggle" }
    );
    return list;
  }, [games, chipTournamentGame, tournamentId, discipline, mapGame, tournamentsQuery.data, mapsQuery.data, t, tGame]);

  const filters = useFilters(defs);
  // Read only while the map chip is declared, i.e. while a game is known.
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
        header: t("map"),
        // The server sorts none of these, so offering a sort control would be a
        // lie the header cannot honour.
        enableSorting: false,
        cell: ({ row }) => (
          <div className="min-w-0 max-w-[20rem]">
            <p className="truncate font-medium text-foreground" title={mapWithModeName(row.original.map, row.original.mode)}>
              {mapWithModeName(row.original.map, row.original.mode)}
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
      ...(discipline === null
        ? [gameColumn<AdminMatchRow>(tGame("column"), (row) => row.discipline)]
        : []),
      {
        id: "score",
        header: t("score"),
        size: 92,
        enableSorting: false,
        cell: ({ row }) => (
          <span className="text-sm tabular-nums text-foreground">{scoreLine(row.original.participants)}</span>
        )
      },
      {
        // The raw log and where it stands: the file name, plus a pill only
        // while ingestion still wants something; a map with no linked job says so.
        id: "log",
        header: t("log"),
        enableSorting: false,
        cell: ({ row }) => {
          const record = row.original.log_record;
          if (!record) return <StatusIcon icon={FileQuestion} label={t("noRawLog")} variant="muted" />;
          return (
            <div className="flex min-w-0 items-center gap-2">
              {row.original.log_name ? (
                <p
                  className="max-w-[18rem] truncate font-mono text-xs text-muted-foreground"
                  title={row.original.log_name}
                >
                  {row.original.log_name}
                </p>
              ) : null}
              <LogStatusPill status={record.status} />
            </div>
          );
        }
      }
    ],
    [showTournament, discipline, t, tGame]
  );

  if (workspaceId == null) {
    return <PageStateCard state="empty" description={t("scopePrompt")} />;
  }

  return (
    <div className="space-y-3">
      <div
        className={cn("grid items-start gap-4", openRow && "lg:grid-cols-[minmax(0,1fr)_380px]")}
      >
        <div className="min-w-0">
          <DataTable<AdminMatchRow>
            columns={columns}
            filterKey={filters.filterKey}
            initialPageSize={PAGE_SIZE}
            searchPlaceholder={t("search")}
            inspectorId={openId}
            getRowId={(row) => String(row.id)}
            toolbar={
              <FilterBar defs={defs} filters={filters} />
            }
            emptyMessage={
              unlinkedOnly
                ? t("emptyNoRawLog")
                : t("empty")
            }
            onRowClick={(row) => setParams({ id: String(row.original.id) })}
            renderMobileCard={(row) => (
              <div className="min-w-0 flex-1 space-y-0.5">
                <p className="truncate text-sm font-medium">{mapWithModeName(row.original.map, row.original.mode)}</p>
                {discipline === null ? (
                  <RowGameLabel code={row.original.discipline} className="flex text-xs text-muted-foreground" />
                ) : null}
                <p className="truncate text-xs text-muted-foreground">
                  {row.original.encounter_name} ·{" "}
                  <span className="tabular-nums">{scoreLine(row.original.participants)}</span>
                </p>
                {row.original.log_record ? (
                  <LogStatusPill status={row.original.log_record.status} />
                ) : (
                  <StatusIcon icon={FileQuestion} label={t("noRawLog")} variant="muted" />
                )}
              </div>
            )}
            queryKey={(page, search, pageSize) => [
              "admin-matches",
              {
                workspaceId,
                tournamentId: scopeTournamentId,
                chip: unlinkedOnly ? "no-raw-log" : "all",
                page,
                search,
                pageSize,
                filters: { map_id: mapFilter, log_status: statusFilter, discipline }
              }
            ]}
            queryFn={(page, search, pageSize) =>
              adminService.listAdminMatches({
                workspace_id: workspaceId,
                tournament_id: scopeTournamentId ?? undefined,
                query: search || undefined,
                discipline: discipline ?? undefined,
                map_id: mapFilter ? Number(mapFilter) : undefined,
                log_status: statusFilter.length ? statusFilter : undefined,
                ...(unlinkedOnly && { unlinked_only: true }),
                page,
                per_page: pageSize
              })
            }
            onPageRowsChange={setPageRows}
          />
        </div>

        <Inspector
          openId={openRow ? openId : null}
          onClose={() => setParams({ id: null })}
          title={openRow ? mapWithModeName(openRow.map, openRow.mode) : ""}
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
