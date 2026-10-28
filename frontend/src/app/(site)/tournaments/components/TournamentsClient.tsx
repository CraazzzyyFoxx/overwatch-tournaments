"use client";

import { useEffect, useMemo, useState } from "react";
import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useDebounce } from "use-debounce";

import tournamentService from "@/services/tournament.service";
import encounterService from "@/services/encounter.service";
import statisticsService from "@/services/statistics.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import { TOURNAMENT_STATUS_ORDER } from "@/lib/tournament/status";
import type { TournamentStatus } from "@/types/tournament.types";
import { Skeleton } from "@/components/ui/skeleton";
import { InfiniteScrollFooter } from "@/components/ui/infinite-scroll";
import { PageStateCard } from "@/components/ui/page-state-card";
import { useQueryParams } from "@/hooks/useQueryParams";
import type { StatsScope } from "@/lib/site/stats-scope";
import { showsGameMarks, type GameScopeInit } from "@/lib/site/discipline-scope";
import { useGameScope } from "@/hooks/useGameScope";
import { useGameDescriptors } from "@/hooks/useGameDescriptors";
import { GameScopeControl } from "@/components/workspace/GameScopeControl";

import TournamentsHero from "./TournamentsHero";
import FeaturedLive from "./FeaturedLive";
import TournamentsFilters, {
  type SortBy,
  type StatusFilter,
  type TypeFilter,
  type ViewMode
} from "./TournamentsFilters";
import TournamentsGrid from "./TournamentsGrid";
import TournamentsTable from "./TournamentsTable";
import { groupLiveByTournament } from "./tournaments-helpers";

/** Divides by 2, 3 and 4, so the card grid never ends on a ragged row. */
const PER_PAGE = 12;

const SORT_BY: readonly SortBy[] = ["latest", "oldest", "participants"];
const TYPE_FILTERS: readonly TypeFilter[] = ["all", "standard", "league"];
const VIEWS: readonly ViewMode[] = ["cards", "list"];

/**
 * What the sort control means in wire terms. `participants` has no ascending
 * counterpart on purpose: "fewest participants" is not a question anyone asks
 * of a tournament list.
 */
const SORT_QUERY: Record<SortBy, { sort: "start_date" | "participants_count"; order: "asc" | "desc" }> = {
  latest: { sort: "start_date", order: "desc" },
  oldest: { sort: "start_date", order: "asc" },
  participants: { sort: "participants_count", order: "desc" }
};

/** Chip counts before the facets land, so the toolbar never renders `NaN`. */
const NO_STATUS_COUNTS: Record<TournamentStatus, number> = {
  announcement: 0,
  draft: 0,
  registration: 0,
  check_in: 0,
  live: 0,
  playoffs: 0,
  completed: 0,
  archived: 0
};

const TournamentsPageSkeleton = () => (
  <div className="space-y-6">
    <Skeleton className="h-[200px] w-full rounded-2xl" />
    <Skeleton className="h-12 w-full rounded-xl" />
    <Skeleton className="h-[520px] w-full rounded-xl" />
  </div>
);

const TournamentsClient = ({
  scope,
  initial
}: Readonly<{ scope: StatsScope; initial?: GameScopeInit }>) => {
  const t = useTranslations();
  const currentWorkspaceId = useWorkspaceStore((s) => s.currentWorkspaceId);
  const workspaces = useWorkspaceStore((s) => s.workspaces);
  // One value carries the workspace dimension of every read and its cache key.
  const workspaceId: number | "all" | null = scope === "all" ? "all" : currentWorkspaceId;
  const workspaceName =
    scope === "all"
      ? t("common.scope.all")
      : workspaces.find((w) => w.id === currentWorkspaceId)?.name;

  // The directory's game (spec §4.3, multi): `?discipline=`, else the saved scope, else every game. Only the list
  // and its facets know games server-side; they wait for the resolution and never read a guessed one.
  const gameScope = useGameScope({ initial });
  const resolution = gameScope.resolution;
  const disciplineFilter = gameScope.game;
  const disciplineKey = disciplineFilter ?? "all";
  const ready = resolution?.game.kind === "all" || resolution?.game.kind === "game";
  // Under every game of a multi-game area each card names its game (§6.1).
  const descriptors = useGameDescriptors();
  const games = resolution !== null && showsGameMarks(resolution, gameScope.games ?? []) ? descriptors : undefined;

  // Filters live in the URL, so a filtered view survives a reload and can be
  // shared. Scroll depth deliberately does NOT: it belongs to the query cache,
  // and a `?page=` that only ever grew would promise a resumable position the
  // page cannot restore.
  const { searchParams, setParams } = useQueryParams();

  const statusParam = searchParams?.get("status");
  const statusFilter: StatusFilter =
    statusParam && (TOURNAMENT_STATUS_ORDER as string[]).includes(statusParam)
      ? (statusParam as TournamentStatus)
      : "all";

  const typeParam = searchParams?.get("type");
  const typeFilter: TypeFilter = TYPE_FILTERS.includes(typeParam as TypeFilter)
    ? (typeParam as TypeFilter)
    : "all";

  const viewParam = searchParams?.get("view");
  const view: ViewMode = VIEWS.includes(viewParam as ViewMode) ? (viewParam as ViewMode) : "cards";

  const sortParam = searchParams?.get("sort");
  const sortBy: SortBy = SORT_BY.includes(sortParam as SortBy) ? (sortParam as SortBy) : "latest";

  // The field is local and the URL follows it, debounced. Filtering used to
  // happen in the browser over the whole table, so writing `?q=` per keystroke
  // cost nothing; now every distinct value is two network round-trips (list +
  // facets), so the debounced value — not the input's — is what reaches the
  // query keys.
  const searchParam = searchParams?.get("q") ?? "";
  const [searchInput, setSearchInput] = useState(searchParam);
  const [debouncedSearch] = useDebounce(searchInput, 300);
  const query = debouncedSearch.trim();

  useEffect(() => {
    if (query === searchParam.trim()) return;
    setParams({ q: query || null });
    // `setParams` is recreated whenever the query string changes, and
    // `searchParam` is read from it; depending on either would re-run this on
    // every unrelated filter change and fight the writer that caused it.
  }, [query]);

  const hasActiveFilters = statusFilter !== "all" || typeFilter !== "all" || query !== "";
  const clearFilters = () => {
    setSearchInput("");
    setParams({ status: null, type: null, q: null });
  };

  const filterQuery = {
    workspaceId,
    status: statusFilter === "all" ? undefined : statusFilter,
    isLeague: typeFilter === "all" ? undefined : typeFilter === "league",
    query: query || undefined,
    discipline: disciplineFilter
  };

  const {
    data: listPages,
    isLoading,
    isError,
    refetch,
    hasNextPage,
    isFetchingNextPage,
    isFetchNextPageError,
    fetchNextPage
  } = useInfiniteQuery({
    // Every filter is in the key: a narrowed filter is a different list, so the
    // pages already accumulated for the old one must not carry over.
    queryKey: tournamentQueryKeys.listPage(workspaceId, disciplineKey, statusFilter, typeFilter, query, sortBy),
    queryFn: ({ pageParam, signal }) =>
      tournamentService.listTournaments(
        {
          ...filterQuery,
          ...SORT_QUERY[sortBy],
          page: pageParam,
          perPage: PER_PAGE
        },
        { signal }
      ),
    enabled: ready,
    initialPageParam: 1,
    getNextPageParam: (lastPage, pages) => {
      // An empty page also ends the run: without that guard a `total` that
      // disagrees with the rows (a row hidden between two requests) would keep
      // asking for a page that can never arrive.
      if (lastPage.results.length === 0) return undefined;
      const loaded = pages.reduce((count, page) => count + page.results.length, 0);
      return loaded < lastPage.total ? pages.length + 1 : undefined;
    }
  });

  const { data: facets } = useQuery({
    queryKey: tournamentQueryKeys.facets(workspaceId, disciplineKey, statusFilter, typeFilter, query),
    queryFn: ({ signal }) => tournamentService.getFacets(filterQuery, { signal }),
    enabled: ready
  });

  const { data: overview } = useQuery({
    queryKey: tournamentQueryKeys.encountersOverview(workspaceId, disciplineFilter),
    queryFn: () => encounterService.getOverview("", { discipline: disciplineFilter }, workspaceId),
    enabled: ready,
    refetchInterval: 30_000,
    staleTime: 15_000
  });

  // Platform-wide totals have no per-game reader: they are shown for all games only.
  const { data: overall } = useQuery({
    queryKey: tournamentQueryKeys.overallStatistics(workspaceId),
    queryFn: () =>
      statisticsService.getOverallStatistics(workspaceId != null ? { workspaceId } : undefined),
    enabled: resolution?.game.kind === "all"
  });

  const results = useMemo(
    () => listPages?.pages.flatMap((page) => page.results) ?? [],
    [listPages]
  );

  // The overview is read for the chosen game, so its live strip is that game's before the server limit.
  const liveGroups = useMemo(() => groupLiveByTournament(overview?.live ?? []), [overview]);

  if (resolution === null) {
    return gameScope.isError ? (
      <div className="text-body">
        <PageStateCard state="error" headingLevel={1} onAction={gameScope.refetch} />
      </div>
    ) : (
      <div className="text-body">
        <TournamentsPageSkeleton />
      </div>
    );
  }

  if (resolution.game.kind === "invalid" || resolution.game.kind === "empty") {
    return (
      <div className="text-body">
        <GameScopeControl scope={gameScope} variant="multi" headingLevel={1} />
      </div>
    );
  }

  if (isLoading) {
    return (
      <div className="text-body">
        <TournamentsPageSkeleton />
      </div>
    );
  }

  // How many tournaments the current filter matches server-side — NOT how many
  // are on screen. The accumulated array only ever knows the pages fetched so
  // far, so reading its length would count down the scroll instead of stating
  // the size of the result set.
  const matchedTotal = listPages?.pages[0]?.total ?? 0;

  return (
    <div className="space-y-6 text-body">
      <TournamentsHero
        workspaceName={workspaceName}
        liveEvents={facets?.live ?? 0}
        totalPlayers={disciplineFilter === null ? (overall?.players ?? 0) : null}
        totalTeams={disciplineFilter === null ? (overall?.teams ?? 0) : null}
      />

      <FeaturedLive groups={liveGroups} />

      <TournamentsFilters
        total={facets?.total ?? 0}
        statusCounts={facets?.by_status ?? NO_STATUS_COUNTS}
        statusFilter={statusFilter}
        onStatusChange={(value) => setParams({ status: value === "all" ? null : value })}
        typeFilter={typeFilter}
        leagueCount={facets?.league ?? 0}
        standardCount={facets?.standard ?? 0}
        onTypeChange={(value) => setParams({ type: value === "all" ? null : value })}
        search={searchInput}
        onSearchChange={setSearchInput}
        sortBy={sortBy}
        onSortChange={(value) => setParams({ sort: value === "latest" ? null : value })}
        view={view}
        onViewChange={(value) => setParams({ view: value === "cards" ? null : value })}
      />

      {isError ? (
        <PageStateCard state="error" onAction={() => void refetch()} />
      ) : results.length === 0 ? (
        hasActiveFilters ? (
          <PageStateCard
            state="filtered-empty"
            title={t("tournamentsList.empty.title")}
            description={t("tournamentsList.empty.body")}
            onAction={clearFilters}
          />
        ) : (
          <PageStateCard state="empty" />
        )
      ) : (
        <>
          {view === "list" ? (
            /* Both layouts, one chosen by the viewport. Below `md` the table
               shows two of its six columns, so the cards are the mobile list
               whatever `?view=` says — and a JS media query would have to flash
               the wrong one through hydration first. */
            <>
              <TournamentsTable tournaments={results} games={games} className="max-md:hidden" />
              <TournamentsGrid tournaments={results} games={games} className="md:hidden" />
            </>
          ) : (
            <TournamentsGrid tournaments={results} games={games} />
          )}

          <InfiniteScrollFooter
            loaded={results.length}
            total={matchedTotal}
            unit={t("tournamentsList.footer.unit")}
            hasNextPage={hasNextPage}
            isFetchingNextPage={isFetchingNextPage}
            isError={isFetchNextPageError}
            fetchNextPage={() => void fetchNextPage()}
            loadMoreLabel={t("tournamentsList.footer.loadMore", {
              count: matchedTotal - results.length
            })}
            progressLabel={t("tournamentsList.footer.progress", {
              loaded: results.length,
              total: matchedTotal
            })}
            errorLabel={t("tournamentsList.footer.error")}
            size="lg"
          />
        </>
      )}
    </div>
  );
};

export default TournamentsClient;
