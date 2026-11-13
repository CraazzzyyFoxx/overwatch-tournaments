"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";
import { cn } from "@/lib/utils";

import userService from "@/services/user.service";
import { UserMapsSummary } from "@/types/user.types";
import { CardSurface, ProfileStat } from "@/components/profile/atoms";
import MapRow from "@/app/(site)/users/components/maps/MapRow";
import MapsFilters from "@/app/(site)/users/components/maps/MapsFilters";
import { DataPagination } from "@craazzzyyfoxx/admin-kit/ui/data-pagination";
import { Eyebrow } from "@craazzzyyfoxx/admin-kit/ui/eyebrow";
import { RowButton } from "@craazzzyyfoxx/admin-kit/ui/row-button";
import { Skeleton } from "@craazzzyyfoxx/admin-kit/ui/skeleton";
import { winrateColor } from "@/lib/colors";
import { userQueryKeys } from "@/lib/users/query-keys";
import type { StatsScope } from "@/lib/site/stats-scope";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";

interface Props {
  userId: number;
  /** The game's profile tournaments: the tournament filter's options. */
  tournaments: { id: number; name: string }[];
  scope: StatsScope;
  discipline: string;
  /** The viewed workspace axis the game's metadata is read on. */
  axis: WorkspaceAxis;
}

const MODE_ORDER = ["Control", "Escort", "Hybrid", "Flashpoint", "Push", "Assault"] as const;

type SortKey = "winrate" | "count" | "name";
type OrderKey = "asc" | "desc";

const MapsView = ({ userId, tournaments, scope, discipline, axis }: Props) => {
  const t = useTranslations();
  const [modeFilter, setModeFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebounce(search, 300);
  const [sort, setSort] = useState<SortKey>("winrate");
  const [order, setOrder] = useState<OrderKey>("desc");
  const [minCount, setMinCount] = useState(1);
  const [perPage, setPerPage] = useState(15);
  const [page, setPage] = useState(1);
  const [tournamentId, setTournamentId] = useState<number | undefined>(undefined);

  // Reset to first page whenever any filter/sort that changes the result set moves.
  // Render-time adjustment (React-recommended) instead of an effect with setState.
  const filterKey = `${modeFilter}|${sort}|${order}|${minCount}|${perPage}|${tournamentId}|${debouncedSearch}`;
  const [prevFilterKey, setPrevFilterKey] = useState(filterKey);
  if (filterKey !== prevFilterKey) {
    setPrevFilterKey(filterKey);
    setPage(1);
  }

  const mapFilters = { query: debouncedSearch, minCount, tournamentId };
  const mapsQuery = useQuery({
    queryKey: userQueryKeys.maps(userId, scope, discipline, mapFilters),
    queryFn: () =>
      userService.getUserMaps(userId, discipline, {
        page: 1,
        perPage: -1,
        sort: "winrate",
        order: "desc",
        query: debouncedSearch.trim(),
        minCount,
        tournamentId,
        scope
      }),
    staleTime: 60_000
  });

  const summaryQuery = useQuery({
    queryKey: userQueryKeys.mapsSummary(userId, scope, discipline, mapFilters),
    queryFn: () =>
      userService.getUserMapsSummary(userId, discipline, {
        query: debouncedSearch.trim(),
        minCount,
        tournamentId,
        scope
      }),
    staleTime: 60_000
  });

  const summary = summaryQuery.data as UserMapsSummary | undefined;
  const allMaps = mapsQuery.data?.results ?? [];

  // Aggregate by gamemode (over the full, tournament-scoped set).
  const modeStats = useMemo(() => {
    const buckets = new Map<
      string,
      { mode: string; maps: Set<number>; games: number; win: number; loss: number; draw: number }
    >();
    allMaps.forEach((row) => {
      const mode = row.map.parent?.name ?? t("common.unknown");
      const b = buckets.get(mode) ?? { mode, maps: new Set<number>(), games: 0, win: 0, loss: 0, draw: 0 };
      b.maps.add(row.map.id);
      b.games += row.count;
      b.win += row.win;
      b.loss += row.loss;
      b.draw += row.draw;
      buckets.set(mode, b);
    });
    return Array.from(buckets.values()).sort((a, b) => {
      const ai = MODE_ORDER.findIndex((m) => m === a.mode);
      const bi = MODE_ORDER.findIndex((m) => m === b.mode);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    });
  }, [allMaps, t]);

  const sortedMaps = useMemo(() => {
    let rows = [...allMaps];
    if (modeFilter) rows = rows.filter((r) => r.map.parent?.name === modeFilter);
    rows.sort((a, b) => {
      let cmp = 0;
      if (sort === "winrate") cmp = a.win_rate - b.win_rate;
      else if (sort === "count") cmp = a.count - b.count;
      else cmp = a.map.name.localeCompare(b.map.name);
      return order === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [allMaps, modeFilter, sort, order]);

  const totalCount = sortedMaps.length;
  const pages = perPage === -1 ? 1 : Math.max(1, Math.ceil(totalCount / perPage));
  const pageMaps = perPage === -1 ? sortedMaps : sortedMaps.slice((page - 1) * perPage, page * perPage);

  const overall = summary?.overall;

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      {/* Top stats */}
      <CardSurface>
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 md:grid-cols-4">
          <ProfileStat
            label={t("users.maps.overallWinrate")}
            value={overall ? `${(overall.win_rate * 100).toFixed(1)}%` : "—"}
            color={overall ? winrateColor(overall.win_rate * 100) : undefined}
            sub={
              overall
                ? `${overall.win}-${overall.loss}-${overall.draw} · ${t("users.maps.gamesCount", { count: overall.total_games })}`
                : "—"
            }
          />
          <ProfileStat
            label={t("users.maps.mostPlayed")}
            value={
              summary?.most_played ? (
                <>
                  {summary.most_played.count}
                  <span className="text-title text-[color:var(--aqt-fg-faint)]">{t("users.maps.gamesUnit")}</span>
                </>
              ) : (
                "—"
              )
            }
            sub={
              summary?.most_played
                ? [summary.most_played.map.name, summary.most_played.map.parent?.name].filter(Boolean).join(" · ")
                : "—"
            }
          />
          <ProfileStat
            label={t("users.maps.bestMap")}
            value={summary?.best ? `${(summary.best.win_rate * 100).toFixed(0)}%` : "—"}
            color={summary?.best ? winrateColor(summary.best.win_rate * 100) : undefined}
            sub={
              summary?.best
                ? `${summary.best.map.name} · ${t("users.maps.gamesShort", { count: String(summary.best.count) })}`
                : "—"
            }
          />
          <ProfileStat
            label={t("users.maps.weakest")}
            value={summary?.worst ? `${(summary.worst.win_rate * 100).toFixed(0)}%` : "—"}
            color={summary?.worst ? winrateColor(summary.worst.win_rate * 100) : undefined}
            sub={
              summary?.worst
                ? `${summary.worst.map.name} · ${t("users.maps.gamesShort", { count: String(summary.worst.count) })}`
                : "—"
            }
          />
        </div>
      </CardSurface>

      {/* Mode breakdown */}
      <CardSurface
        title={t("users.maps.byMode")}
        subtitle={t("users.maps.byModeSubtitle", {
          modes: modeStats.length,
          games: allMaps.reduce((s, m) => s + m.count, 0)
        })}
      >
        <div className="-m-2 grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 xl:grid-cols-6">
          {modeStats.map((b) => {
            const totalDecisive = b.win + b.loss;
            const wr = totalDecisive > 0 ? (b.win / totalDecisive) * 100 : 0;
            const active = modeFilter === b.mode;
            return (
              <RowButton
                key={b.mode}
                onClick={() => setModeFilter(active ? null : b.mode)}
                aria-pressed={active}
                title={active ? t("users.maps.clearModeFilter") : t("users.maps.filterByMode", { mode: b.mode })}
                className={cn("rounded-lg p-2", active && "bg-[color:var(--aqt-overlay-3)]")}
              >
                <ProfileStat
                  size="md"
                  label={<span style={active ? { color: "var(--aqt-teal)" } : undefined}>{b.mode}</span>}
                  value={`${wr.toFixed(0)}%`}
                  color={totalDecisive > 0 ? winrateColor(wr) : undefined}
                  sub={`${b.win}-${b.loss} · ${t("users.maps.mapsCount", { count: b.maps.size })} · ${t("users.maps.gamesCount", { count: b.games })}`}
                >
                  <div className="mt-1 h-1 w-full rounded-full bg-[color:var(--aqt-border)]">
                    <div
                      className="h-full rounded-full bg-[color:var(--aqt-fg-faint)]"
                      style={{ width: `${wr}%` }}
                    />
                  </div>
                </ProfileStat>
              </RowButton>
            );
          })}
        </div>
      </CardSurface>

      {/* Filter chips + controls */}
      <MapsFilters
        tournamentId={tournamentId}
        onTournamentIdChange={setTournamentId}
        tournaments={tournaments}
        minCount={minCount}
        onMinCountChange={setMinCount}
        perPage={perPage}
        onPerPageChange={setPerPage}
        sort={sort}
        onSortChange={setSort}
        order={order}
        onOrderToggle={() => setOrder((o) => (o === "asc" ? "desc" : "asc"))}
        search={search}
        onSearchChange={setSearch}
      />

      {/* Map rows */}
      <CardSurface flush>
        <Eyebrow
          as="div"
          className="grid grid-cols-[64px_1fr_1fr_minmax(0,1.2fr)_60px_50px] items-center gap-3.5 border-b border-[color:var(--aqt-border)] px-[18px] py-3"
        >
          <div />
          <div>{t("users.maps.colMap")}</div>
          <div>{t("users.maps.colWinrate")}</div>
          <div>{t("common.characters")}</div>
          <div className="text-right">{t("users.maps.colRecord")}</div>
          <div className="text-right">{t("users.maps.colGames")}</div>
        </Eyebrow>
        {pageMaps.map((row) => (
          <MapRow key={row.map.id} row={row} discipline={discipline} axis={axis} />
        ))}
        {pageMaps.length === 0 ? (
          mapsQuery.isLoading ? (
            <div role="status">
              <span className="sr-only">{t("common.loading")}</span>
              {[0, 1, 2, 3, 4].map((row) => (
                <div
                  key={row}
                  aria-hidden
                  className="flex items-center gap-3.5 border-b border-[color:var(--aqt-border)] px-[18px] py-[11px] last:border-b-0"
                >
                  <Skeleton className="h-8 w-14" />
                  <Skeleton className="h-4 flex-1" />
                </div>
              ))}
            </div>
          ) : (
            <div className="py-10 text-center text-[color:var(--aqt-fg-dim)]">{t("users.maps.noMaps")}</div>
          )
        ) : null}

        {/* Pagination footer */}
        {perPage !== -1 && totalCount > 0 ? (
          <DataPagination
            page={page}
            totalPages={pages}
            onPageChange={setPage}
            className="border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-[18px] py-3.5"
            leading={
              <span className="aqt-tnum text-caption text-[color:var(--aqt-fg-dim)]">
                {t("common.showingRange", {
                  start: String((page - 1) * perPage + 1),
                  end: String(Math.min(page * perPage, totalCount)),
                  total: String(totalCount)
                })}
              </span>
            }
          />
        ) : null}
      </CardSurface>
    </div>
  );
};

export default MapsView;
