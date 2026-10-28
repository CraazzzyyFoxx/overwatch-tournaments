"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Building2,
  ClipboardList,
  EyeOff,
  Gamepad2,
  NotebookPen,
  Radar,
  Shuffle,
  Trophy,
  Users,
  type LucideIcon,
} from "lucide-react";

import DivisionIcon from "@/components/DivisionIcon";
import { DivisionRangePicker } from "@/components/DivisionRangePicker";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { gameFilterDefs } from "@/components/admin/game-filter";
import { DataTable, columnMeta } from "@/components/data-table";
import { EmptyNote } from "@/components/kit/EmptyNote";
import { FilterBar } from "@/components/kit/FilterBar";
import { formatDate } from "@/components/kit/format-time";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";
import { DateRangePicker } from "@/components/ui/date-range-picker";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";
import { RowGameLabel, gameColumn } from "@/components/workspace/game-column";
import { useGameScope } from "@/hooks/useGameScope";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useQueryParams } from "@/hooks/useQueryParams";
import { useSlotLabel } from "@/hooks/useSlotLabel";
import { adminQueryKeys } from "@/lib/admin/query-keys";
import { useFormatter } from "@/lib/datetime/client";
import { ALL_DISCIPLINES, type WorkspaceAxis } from "@/lib/site/discipline-scope";
import { getDivisionLabel } from "@/lib/divisions/grid";
import { findRole, ratedDimension, registrationRoles } from "@/lib/roster/ontology";
import { OPEN_SLOT_CODE } from "@/lib/roster/shape";
import {
  RANK_LAYERS,
  workspacePlayerKeys,
  workspacePlayerService,
  type RankLayer,
  type RankOverviewRow,
} from "@/services/workspace-player.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { DisciplineDescriptor, DisciplineMetadata } from "@/types/discipline.types";

const PAGE_SIZE = 30;

const LAYER_ICON: Record<RankLayer, LucideIcon> = {
  canon: Building2,
  author: NotebookPen,
  native: Radar,
  hidden: EyeOff,
  effective_tournament: Trophy,
  effective_mix: Shuffle,
  registration: ClipboardList,
  tournament: Users,
  casual: Gamepad2,
};

/** Dates live outside `useFilters` (the chip bar has no range kind), so they reset the page themselves. */
const DATE_PARAMS = { from: "date_from", to: "date_to" } as const;

/** Signs a delta the way a reader expects: "+120", "-80", "0". */
const signedDelta = (value: number) => (value > 0 ? `+${value}` : String(value));

/** The role and division filters are one game's: a pick of another game leaves them behind (R5). */
const RANK_GAME_PARAMS = ["role", "div_min", "div_max"];
/** Rank and division orders live on one game's grid: the all-games read never asks for them (spec §6.8). */
const GAME_BOUND_SORTS: readonly string[] = ["rank_value", "division"];

/**
 * The workspace's rank values (spec §6.8, a multi surface on `/admin/ranks`). The game is the bar's first chip
 * (`?discipline=`). Under a game: that game's rows, its role and division-range filters and every sort. Under "all
 * games": every enabled game's rows with a game column; role and division stay in each row (facts of the record, drawn
 * on the row's own game), the role and division-range filters and the rank sorts step aside. An invalid or empty
 * resolution reads nothing. Switching game remounts the rows, so no row of the previous one lingers.
 */
export function RankOverviewTable() {
  const t = useTranslations("admin.rankOverview");
  const workspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  const scope = useGameScope({ pageClass: "multi", axis: workspaceId ?? "all" });
  const kind = scope.resolution?.game.kind;
  const discipline = scope.game;
  const metadata = useDisciplineMetadata(scope.axis, discipline);

  if (workspaceId == null) {
    return <EmptyNote>{t("noWorkspace")}</EmptyNote>;
  }
  if (kind === "invalid" || kind === "empty") {
    return <GameScopeControl scope={scope} variant="multi" dropParams={RANK_GAME_PARAMS} />;
  }
  if (scope.isError || metadata.isError) {
    return (
      <PageStateCard
        state="error"
        title={t("loadError")}
        onAction={() => {
          scope.refetch();
          void metadata.refetch();
        }}
      />
    );
  }
  if (kind === undefined || (kind === "game" && !metadata.data)) {
    return <Skeleton className="h-64" />;
  }
  return (
    <RankOverviewRows
      key={`${workspaceId}:${discipline ?? ALL_DISCIPLINES}`}
      workspaceId={workspaceId}
      axis={scope.axis}
      discipline={discipline}
      ontology={metadata.data ?? null}
      games={scope.games ?? []}
    />
  );
}

/** A row's person, linking to their person page. */
function RowPlayer({ row }: Readonly<{ row: RankOverviewRow }>) {
  return (
    <Link
      href={`/admin/people/${row.player_id}`}
      className="font-medium text-primary underline-offset-2 hover:underline"
      onClick={(event) => event.stopPropagation()}
    >
      {row.display_name || row.identity?.handle || `#${row.player_id}`}
    </Link>
  );
}

/** A row's layer. */
function RowLayer({ row }: Readonly<{ row: RankOverviewRow }>) {
  const t = useTranslations("admin.rankOverview");
  const Icon = LAYER_ICON[row.layer];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs">
      <Icon className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />
      {t(`layers.${row.layer}`)}
    </span>
  );
}

/** A row's role, drawn from its own game's dictionary; a role that dictionary does not know stays its raw code. */
function RowRole({ role, discipline, axis }: Readonly<{ role: string | null; discipline: string; axis: WorkspaceAxis }>) {
  const ontology = useDisciplineMetadata(axis, discipline).data ?? null;
  if (!role) return null;
  const rated = ontology ? ratedDimension(ontology) : null;
  const known =
    role === OPEN_SLOT_CODE ||
    (ontology !== null && rated !== null && findRole(ontology, { dimension: rated.code, role }) !== null);
  return known ? (
    <span className="inline-flex">
      <PlayerRoleIcon role={role} ontology={ontology} size={18} />
    </span>
  ) : (
    <span className="text-xs">{role}</span>
  );
}

/** A row's division on its own game's workspace grid, the native ladder's naming beside it. */
function RowDivision({ row }: Readonly<{ row: RankOverviewRow }>) {
  const tBracket = useTranslations("adminBracket");
  const grid = useDivisionGrid(row.discipline);
  const { division, native_division: nativeDivision, native_tier: nativeTier } = row;
  return (
    <div className="flex items-center gap-2">
      {division == null ? null : (
        <>
          <DivisionIcon division={division} tournamentGrid={grid} width={20} height={20} />
          <span className="truncate">
            {getDivisionLabel(grid, division) ?? tBracket("labels.divisionFallback", { number: division })}
          </span>
        </>
      )}
      {nativeDivision ? (
        // The native ladder's own naming, kept beside the workspace grid's:
        // the two disagree, and the scrape is only readable as itself.
        <span className="whitespace-nowrap text-xs capitalize text-muted-foreground">
          {nativeDivision}
          {nativeTier == null ? "" : ` ${nativeTier}`}
        </span>
      ) : null}
    </div>
  );
}

/**
 * Every rank value in scope, one row per value: canon, each author's book, the
 * native-ladder scrape (for a game that collects one), the hidden rating, both
 * computed effective numbers, and the three historical layers.
 *
 * Read-only on purpose. Editing a rank has two owners already (the roster's
 * rank editor and a person's own panel), and a table that mixes nine layers —
 * three of which are computed and cannot be written at all — is the wrong place
 * to grow a third. Filters, sort and page live in the URL.
 */
function RankOverviewRows({
  workspaceId,
  axis,
  discipline,
  ontology,
  games,
}: Readonly<{
  workspaceId: number;
  axis: WorkspaceAxis;
  /** One game, or `null` under "all games". */
  discipline: string | null;
  /** The game's metadata; `null` under "all games". */
  ontology: DisciplineMetadata | null;
  games: readonly DisciplineDescriptor[];
}>) {
  const t = useTranslations("admin.rankOverview");
  const tGame = useTranslations("common.discipline");
  const slotLabel = useSlotLabel(ontology);
  const format = useFormatter();
  const allGames = discipline === null;
  const grid = useDivisionGrid(discipline ?? undefined);
  // Only a game that collects a native rank has that layer.
  const hasNativeRank = games.some(
    (entry) => (allGames || entry.code === discipline) && entry.capabilities.native_rank_collection,
  );
  const { searchParams, setParams } = useQueryParams({ resetOnChange: ["page"] });
  const dateFrom = searchParams?.get(DATE_PARAMS.from) ?? "";
  const dateTo = searchParams?.get(DATE_PARAMS.to) ?? "";
  const sortParam = searchParams?.get("sort") ?? "";

  const authorsQuery = useQuery({
    queryKey: workspacePlayerKeys.authors(workspaceId),
    queryFn: () => workspacePlayerService.listAuthors(workspaceId),
    staleTime: 60_000,
  });

  const defs = useMemo<FilterDef[]>(() => {
    // A game change strands the old game's role, division range and rank order (DataTable's `sort`/`dir`).
    const game = gameFilterDefs(games, tGame("column"), () =>
      GAME_BOUND_SORTS.includes(sortParam) ? [...RANK_GAME_PARAMS, "sort", "dir"] : RANK_GAME_PARAMS,
    );
    const layer: FilterDef = {
      key: "layer",
      label: t("filters.layer"),
      kind: "multi",
      options: RANK_LAYERS.filter((value) => value !== "native" || hasNativeRank).map((value) => ({
        value,
        label: t(`layers.${value}`),
      })),
    };
    const author: FilterDef = {
      key: "author",
      label: t("filters.author"),
      kind: "multi",
      options: (authorsQuery.data?.authors ?? []).map((entry) => ({
        value: String(entry.user_id),
        label: entry.display_name ?? `#${entry.user_id}`,
        count: entry.count,
      })),
    };
    const differs: FilterDef = { key: "differs", label: t("filters.differsFromCanon"), kind: "toggle" };
    // Role is one game's: offered once a game is picked, and the URL's is unread under "all games".
    if (ontology === null) return [...game, layer, author, differs];
    return [
      ...game,
      layer,
      author,
      {
        key: "role",
        label: t("filters.role"),
        kind: "multi",
        options: registrationRoles(ontology).map((role) => ({ value: role.code, label: slotLabel(role.code) })),
      },
      differs,
    ];
  }, [t, tGame, slotLabel, ontology, hasNativeRank, authorsQuery.data, games, sortParam]);

  const filters = useFilters(defs);
  const layerFilter = filters.values.layer as string[];
  const authorFilter = filters.values.author as string[];
  // Absent from `defs` under "all games", so these read nothing there.
  const roleFilter = (filters.values.role as string[] | undefined) ?? [];
  const differsFilter = filters.values.differs === true;
  // The division range lives outside `useFilters` like the dates: tier numbers on the game's workspace grid, sent as
  // they are (the server owns the tier→rank mapping). One game's, so unread under "all games".
  const divMin = allGames ? undefined : Number(searchParams?.get("div_min")) || undefined;
  const divMax = allGames ? undefined : Number(searchParams?.get("div_max")) || undefined;

  const columns = useMemo<ColumnDef<RankOverviewRow>[]>(() => {
    const player: ColumnDef<RankOverviewRow> = {
      id: "display_name",
      header: t("columns.player"),
      meta: columnMeta<RankOverviewRow>({ sticky: true }),
      cell: ({ row }) => <RowPlayer row={row.original} />,
    };

    const rest: ColumnDef<RankOverviewRow>[] = [
      {
        accessorKey: "layer",
        header: t("columns.layer"),
        cell: ({ row }) => <RowLayer row={row.original} />,
      },
      {
        id: "author",
        header: t("columns.author"),
        enableSorting: false,
        cell: ({ row }) =>
          row.original.author_name ??
          (row.original.author_user_id == null ? null : `#${row.original.author_user_id}`),
      },
      {
        accessorKey: "role",
        header: t("columns.role"),
        meta: columnMeta<RankOverviewRow>({ align: "center" }),
        cell: ({ row }) => <RowRole role={row.original.role} discipline={row.original.discipline} axis={axis} />,
      },
      {
        accessorKey: "rank_value",
        header: t("columns.rankValue"),
        // Values of different games live on different grids: no single order across them.
        enableSorting: !allGames,
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) => row.original.rank_value,
      },
      {
        id: "division",
        header: t("columns.division"),
        enableSorting: false,
        cell: ({ row }) => <RowDivision row={row.original} />,
      },
      {
        id: "source",
        header: t("columns.source"),
        enableSorting: false,
        cell: ({ row }) => {
          const source = row.original.source;
          if (!source) return null;
          return (
            <span className="text-xs text-muted-foreground">
              {t(`sources.${source}`)}
            </span>
          );
        },
      },
      {
        accessorKey: "canon_diff",
        header: t("columns.canonDiff"),
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) =>
          row.original.canon_diff == null ? null : signedDelta(row.original.canon_diff),
      },
      {
        accessorKey: "delta",
        header: t("columns.delta"),
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) => (row.original.delta == null ? null : signedDelta(row.original.delta)),
      },
      {
        accessorKey: "sigma",
        header: t("columns.sigma"),
        enableSorting: false,
        meta: columnMeta<RankOverviewRow>({ align: "right", numeric: true }),
        cell: ({ row }) => (row.original.sigma == null ? null : row.original.sigma.toFixed(1)),
      },
      {
        id: "context",
        header: t("columns.context"),
        enableSorting: false,
        cell: ({ row }) => {
          const context = row.original.context;
          if (!context) return null;
          const href =
            context.id == null
              ? null
              : context.kind === "tournament"
                ? `/admin/tournaments/${context.id}`
                : context.kind === "mix"
                  ? `/balancer/mix/${context.id}`
                  : null;
          // On a native-account row `team` is the native platform, not a team name.
          const detail = [
            context.kind === "native_account" ? null : context.team,
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
              {context.kind === "native_account" && context.team ? (
                <span className="truncate text-xs text-muted-foreground">
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

    // Beside the player: which game a row is matters as much as whose it is.
    const game = allGames ? [gameColumn<RankOverviewRow>(tGame("column"), (row) => row.discipline)] : [];
    return [player, ...game, ...rest];
  }, [t, tGame, format, allGames, axis]);

  const activeKey = [
    filters.filterKey,
    dateFrom,
    dateTo,
    divMin && `div_min=${divMin}`,
    divMax && `div_max=${divMax}`,
  ]
    .filter(Boolean)
    .join("&");

  return (
    <DataTable<RankOverviewRow>
      queryKey={(page, search, pageSize, sortField, sortDir) =>
        adminQueryKeys.rankOverview(workspaceId, {
          discipline: discipline ?? ALL_DISCIPLINES,
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
          discipline: discipline ?? undefined,
          page,
          perPage: pageSize,
          query: search || undefined,
          layer: layerFilter,
          authorUserId: authorFilter.map(Number),
          role: roleFilter,
          divMin,
          divMax,
          differsFromCanon: differsFilter || undefined,
          dateFrom: dateFrom || undefined,
          dateTo: dateTo || undefined,
          // A rank sort left in the URL or a saved view is one game's: the all-games read keeps its default order.
          sort: sortField && !(allGames && GAME_BOUND_SORTS.includes(sortField)) ? sortField : undefined,
          order: sortDir,
        })
      }
      columns={columns}
      initialPageSize={PAGE_SIZE}
      initialSort={{ field: "display_name", dir: "asc" }}
      filterKey={activeKey}
      getRowId={(row) =>
        [row.discipline, row.layer, row.member_id, row.author_user_id, row.role, row.at, row.context?.id].join(":")
      }
      searchPlaceholder={t("searchPlaceholder")}
      toolbar={
        <FilterBar
          defs={defs}
          filters={filters}
          extraFilters={
            <>
              {allGames ? null : (
                <div className="w-64">
                  <DivisionRangePicker
                    grid={grid}
                    min={divMin}
                    max={divMax}
                    onChange={(min, max) => setParams({ div_min: min, div_max: max })}
                    ariaLabel={t("filters.divisions")}
                  />
                </div>
              )}
              <div className="w-64">
                <DateRangePicker
                  startDate={dateFrom || undefined}
                  endDate={dateTo || undefined}
                  placeholder={t("filters.dateRange")}
                  size="sm"
                  onChange={(from, to) =>
                    setParams({ [DATE_PARAMS.from]: from || null, [DATE_PARAMS.to]: to || null })
                  }
                />
              </div>
            </>
          }
        />
      }
      emptyMessage={activeKey ? t("emptyFiltered") : t("empty")}
      // Explicit, not the first three columns: a column order saved before the game column existed would push the game
      // off a phone card. Whose value, which game, which layer (and author), then role, value and division.
      renderMobileCard={({ original: row }) => (
        <div className="min-w-0 flex-1 space-y-0.5">
          <p className="truncate text-sm">
            <RowPlayer row={row} />
          </p>
          {allGames ? <RowGameLabel code={row.discipline} className="flex text-xs text-muted-foreground" /> : null}
          <p className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
            <RowLayer row={row} />
            <span className="truncate">
              {row.author_name ?? (row.author_user_id == null ? null : `#${row.author_user_id}`)}
            </span>
          </p>
          <div className="flex items-center gap-2 text-sm tabular-nums">
            <RowRole role={row.role} discipline={row.discipline} axis={axis} />
            {row.rank_value}
            <RowDivision row={row} />
          </div>
        </div>
      )}
    />
  );
}
