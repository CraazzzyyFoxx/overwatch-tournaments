"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";

import DivisionIcon from "@/components/DivisionIcon";
import { DataTable, columnMeta } from "@/components/data-table";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { FilterBar } from "@/components/kit/FilterBar";
import { formatDate } from "@/components/kit/format-time";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { Badge } from "@/components/ui/badge";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useQueryParams } from "@/hooks/useQueryParams";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { getDivisionLabel, getDivisionOptions } from "@/lib/divisions/grid";
import {
  RANK_LAYERS,
  RANK_OVERVIEW_ROLES,
  workspacePlayerKeys,
  workspacePlayerService,
  type RankOverviewRow,
} from "@/services/workspace-player.service";
import { useWorkspaceStore } from "@/stores/workspace.store";

const PAGE_SIZE = 30;

/** Dates live outside `useFilters` (the chip bar has no range kind), so they reset the page themselves. */
const DATE_PARAMS = { from: "date_from", to: "date_to" } as const;

/** Signs a delta the way a reader expects: "+120", "-80", "0". */
const signedDelta = (value: number) => (value > 0 ? `+${value}` : String(value));

export interface RankOverviewTableProps {
  /**
   * Pins the table to one person (`players.user` id). The player column and the
   * search box go with it — both only answer "which person", which is settled.
   */
  playerId?: number;
}

/**
 * Every rank value in the workspace, one row per value: canon, each author's
 * book, the OW scrape, the hidden rating, both computed effective numbers, and
 * the three historical layers.
 *
 * Read-only on purpose. Editing a rank has two owners already (the roster's
 * rank editor and a person's own panel), and a table that mixes nine layers —
 * three of which are computed and cannot be written at all — is the wrong place
 * to grow a third. Filters, sort and page live in the URL, and `useQueryParams`
 * merges rather than replaces, so the person page's `?tab=ranks` survives.
 */
export function RankOverviewTable({ playerId }: Readonly<RankOverviewTableProps>) {
  const t = useTranslations("admin.rankOverview");
  const tRoles = useTranslations("common.roles");
  const format = useFormatter();
  const grid = useDivisionGrid();
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);

  const { searchParams, setParams } = useQueryParams({ resetOnChange: ["page"] });
  const dateFrom = searchParams?.get(DATE_PARAMS.from) ?? "";
  const dateTo = searchParams?.get(DATE_PARAMS.to) ?? "";

  const authorsQuery = useQuery({
    queryKey: workspacePlayerKeys.authors(workspaceId ?? 0),
    queryFn: () => workspacePlayerService.listAuthors(workspaceId as number),
    enabled: workspaceId != null,
    staleTime: 60_000,
  });

  const divisionOptions = useMemo(
    () =>
      getDivisionOptions(grid).map((division) => ({
        value: String(division),
        label: getDivisionLabel(grid, division) ?? String(division),
      })),
    [grid],
  );

  const defs = useMemo<FilterDef[]>(
    () => [
      {
        key: "layer",
        label: t("filters.layer"),
        kind: "multi",
        options: RANK_LAYERS.map((layer) => ({ value: layer, label: t(`layers.${layer}`) })),
      },
      {
        key: "author",
        label: t("filters.author"),
        kind: "multi",
        options: (authorsQuery.data?.authors ?? []).map((author) => ({
          value: String(author.user_id),
          label: author.display_name ?? `#${author.user_id}`,
          count: author.count,
        })),
      },
      {
        key: "role",
        label: t("filters.role"),
        kind: "multi",
        options: RANK_OVERVIEW_ROLES.map((role) => ({ value: role, label: tRoles(role) })),
      },
      // A division band IS a rank range, and the workspace grid is the only
      // honest mapping between them — two numeric inputs would ask the operator
      // to remember that Diamond starts at 3500.
      { key: "div_min", label: t("filters.divisionMin"), kind: "single", options: divisionOptions },
      { key: "div_max", label: t("filters.divisionMax"), kind: "single", options: divisionOptions },
      { key: "differs", label: t("filters.differsFromCanon"), kind: "toggle" },
    ],
    [t, tRoles, authorsQuery.data, divisionOptions],
  );

  const filters = useFilters(defs);
  const layerFilter = filters.values.layer as string[];
  const authorFilter = filters.values.author as string[];
  const roleFilter = filters.values.role as string[];
  const differsFilter = filters.values.differs === true;
  const minTier = grid.tiers.find((tier) => String(tier.number) === filters.values.div_min);
  const maxTier = grid.tiers.find((tier) => String(tier.number) === filters.values.div_max);
  const rankMin = minTier?.rank_min;
  // The top tier is open-ended (`rank_max: null`), which is "no ceiling", not 0.
  const rankMax = maxTier?.rank_max ?? undefined;

  const columns = useMemo<ColumnDef<RankOverviewRow>[]>(() => {
    const player: ColumnDef<RankOverviewRow> = {
      id: "display_name",
      header: t("columns.player"),
      meta: columnMeta<RankOverviewRow>({ sticky: true }),
      cell: ({ row }) => (
        <Link
          href={`/admin/people/${row.original.player_id}`}
          className="font-medium text-primary underline-offset-2 hover:underline"
          onClick={(event) => event.stopPropagation()}
        >
          {row.original.display_name || row.original.battle_tag || `#${row.original.player_id}`}
        </Link>
      ),
    };

    const rest: ColumnDef<RankOverviewRow>[] = [
      {
        accessorKey: "layer",
        header: t("columns.layer"),
        cell: ({ row }) => (
          <Badge variant="outline" className="font-mono text-[11px]">
            {t(`layers.${row.original.layer}`)}
          </Badge>
        ),
      },
      {
        id: "author",
        header: t("columns.author"),
        enableSorting: false,
        cell: ({ row }) =>
          row.original.author_name ??
          (row.original.author_user_id == null ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            `#${row.original.author_user_id}`
          )),
      },
      {
        accessorKey: "role",
        header: t("columns.role"),
        cell: ({ row }) => {
          const role = row.original.role;
          if (!role) return <span className="text-muted-foreground">—</span>;
          const key = role as "tank";
          return tRoles.has(key) ? tRoles(key) : role;
        },
      },
      {
        accessorKey: "rank_value",
        header: t("columns.rankValue"),
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) => row.original.rank_value,
      },
      {
        id: "division",
        header: t("columns.division"),
        enableSorting: false,
        cell: ({ row }) => {
          const { division, ow_division: owDivision, ow_tier: owTier } = row.original;
          return (
            <div className="flex items-center gap-2">
              {division == null ? (
                <span className="text-muted-foreground">—</span>
              ) : (
                <>
                  <DivisionIcon division={division} width={20} height={20} />
                  <span className="truncate">{getDivisionLabel(grid, division) ?? division}</span>
                </>
              )}
              {owDivision ? (
                // The OW ladder's own naming, kept beside the workspace grid's:
                // the two disagree, and the scrape is only readable as itself.
                <span className="whitespace-nowrap text-xs capitalize text-muted-foreground">
                  {owDivision}
                  {owTier == null ? "" : ` ${owTier}`}
                </span>
              ) : null}
            </div>
          );
        },
      },
      {
        id: "source",
        header: t("columns.source"),
        enableSorting: false,
        cell: ({ row }) => {
          const source = row.original.source;
          if (!source) return <span className="text-muted-foreground">—</span>;
          return <span className="text-xs text-muted-foreground">{t(`sources.${source}`)}</span>;
        },
      },
      {
        accessorKey: "canon_diff",
        header: t("columns.canonDiff"),
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) =>
          row.original.canon_diff == null ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            signedDelta(row.original.canon_diff)
          ),
      },
      {
        accessorKey: "delta",
        header: t("columns.delta"),
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) =>
          row.original.delta == null ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            signedDelta(row.original.delta)
          ),
      },
      {
        accessorKey: "sigma",
        header: t("columns.sigma"),
        enableSorting: false,
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) =>
          row.original.sigma == null ? (
            <span className="text-muted-foreground">—</span>
          ) : (
            row.original.sigma.toFixed(1)
          ),
      },
      {
        id: "context",
        header: t("columns.context"),
        enableSorting: false,
        cell: ({ row }) => {
          const context = row.original.context;
          if (!context) return <span className="text-muted-foreground">—</span>;
          const href =
            context.id == null
              ? null
              : context.kind === "tournament"
                ? `/admin/tournaments/${context.id}`
                : context.kind === "mix"
                  ? `/balancer/mix/${context.id}`
                  : null;
          // On a battle-tag row `team` is the OW platform, not a team name.
          const detail = [
            context.kind === "battle_tag" ? null : context.team,
            context.lobby_index == null
              ? null
              : // A..F, the same glyph the mix surface gives a lobby. Spelled out
                // rather than imported: `pickup-chrome` is route-zone code (Z2).
                t("lobby", { letter: String.fromCharCode(65 + context.lobby_index) }),
          ]
            .filter(Boolean)
            .join(" · ");
          return (
            <div className="flex min-w-0 flex-col">
              {href ? (
                <Link
                  href={href}
                  className="truncate text-primary underline-offset-2 hover:underline"
                  onClick={(event) => event.stopPropagation()}
                >
                  {context.label}
                </Link>
              ) : (
                <span className="truncate">{context.label}</span>
              )}
              {detail ? (
                <span className="truncate text-xs text-muted-foreground">{detail}</span>
              ) : null}
              {context.kind === "battle_tag" && context.team ? (
                <span className="truncate text-xs uppercase text-muted-foreground">
                  {context.team}
                </span>
              ) : null}
            </div>
          );
        },
      },
      {
        accessorKey: "at",
        header: t("columns.at"),
        cell: ({ row }) => (
          <span className="whitespace-nowrap text-xs tabular-nums text-muted-foreground">
            {formatDate(format, row.original.at)}
          </span>
        ),
      },
    ];

    return playerId == null ? [player, ...rest] : rest;
  }, [t, tRoles, format, grid, playerId]);

  if (workspaceId == null) {
    return <EmptyNote>{t("noWorkspace")}</EmptyNote>;
  }

  const activeKey = [filters.filterKey, dateFrom, dateTo].filter(Boolean).join("&");

  return (
    <DataTable<RankOverviewRow>
      queryKey={(page, search, pageSize, sortField, sortDir) =>
        adminQueryKeys.rankOverview(workspaceId, {
          playerId,
          page,
          search,
          pageSize,
          sortField,
          sortDir,
          activeKey,
        })
      }
      queryFn={(page, search, pageSize, sortField, sortDir) =>
        workspacePlayerService.listRanks(workspaceId, {
          page,
          perPage: pageSize,
          playerId,
          query: search || undefined,
          layer: layerFilter,
          authorUserId: authorFilter.map(Number),
          role: roleFilter,
          rankMin,
          rankMax,
          differsFromCanon: differsFilter || undefined,
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          sort: sortField ?? undefined,
          order: sortDir,
        })
      }
      columns={columns}
      initialPageSize={PAGE_SIZE}
      initialSort={{ field: "display_name", dir: "asc" }}
      filterKey={activeKey}
      getRowId={(row) =>
        [row.layer, row.member_id, row.author_user_id, row.role, row.at, row.context?.id].join(":")
      }
      searchPlaceholder={playerId == null ? t("searchPlaceholder") : undefined}
      toolbar={
        <FilterBar
          defs={defs}
          filters={filters}
          trailing={
            <div className="w-64">
              <DateRangePicker
                startDate={dateFrom || undefined}
                endDate={dateTo || undefined}
                placeholder={t("filters.dateRange")}
                onChange={(from, to) =>
                  setParams({ [DATE_PARAMS.from]: from || null, [DATE_PARAMS.to]: to || null })
                }
              />
            </div>
          }
        />
      }
      emptyMessage={activeKey ? t("emptyFiltered") : t("empty")}
    />
  );
}
