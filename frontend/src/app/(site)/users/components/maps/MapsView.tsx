"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";
import { cn } from "@/lib/utils";

import userService from "@/services/user.service";
import { UserMapsSummary } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { type SearchableImageOption } from "@/components/ui/searchable-image-select";
import { KPI } from "@/app/(site)/users/components/maps/atoms";
import MapRow from "@/app/(site)/users/components/maps/MapRow";
import MapsFilters from "@/app/(site)/users/components/maps/MapsFilters";
import { DataPagination } from "@/components/ui/data-pagination";
import { LayoutGrid } from "lucide-react";
import { getWinrateColor } from "@/utils/colors";

interface Props {
  userId: number;
}

const MODE_ORDER = ["Control", "Escort", "Hybrid", "Flashpoint", "Push", "Assault"] as const;

type SortKey = "winrate" | "count" | "name";
type OrderKey = "asc" | "desc";

const MapsView = ({ userId }: Props) => {
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

  const tournamentsQuery = useQuery({
    queryKey: ["user-tournaments", userId],
    queryFn: () => userService.getUserTournaments(userId),
    staleTime: 5 * 60 * 1000
  });

  const tournamentOptions = useMemo<SearchableImageOption[]>(
    () => (tournamentsQuery.data ?? []).map((t) => ({ value: String(t.id), label: t.name })),
    [tournamentsQuery.data]
  );

  const mapsQuery = useQuery({
    queryKey: ["user-maps", userId, debouncedSearch, minCount, tournamentId],
    queryFn: () =>
      userService.getUserMaps(userId, {
        page: 1,
        perPage: -1,
        sort: "winrate",
        order: "desc",
        query: debouncedSearch.trim(),
        minCount,
        tournamentId
      }),
    staleTime: 60_000
  });

  const summaryQuery = useQuery({
    queryKey: ["user-maps-summary", userId, debouncedSearch, minCount, tournamentId],
    queryFn: () =>
      userService.getUserMapsSummary(userId, {
        query: debouncedSearch.trim(),
        minCount,
        tournamentId
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
      const mode = row.map.gamemode?.name ?? t("common.unknown");
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
    if (modeFilter) rows = rows.filter((r) => r.map.gamemode?.name === modeFilter);
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

  const modeClass = (mode: string) => {
    const lower = mode.toLowerCase();
    if (lower.includes("control")) return "control";
    if (lower.includes("escort")) return "escort";
    if (lower.includes("hybrid")) return "hybrid";
    if (lower.includes("flashpoint")) return "flashpoint";
    if (lower.includes("push")) return "push";
    return "assault";
  };

  const overall = summary?.overall;

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      {/* Top KPI row */}
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        <KPI
          label={t("users.maps.overallWinrate")}
          value={overall ? `${(overall.win_rate * 100).toFixed(1)}` : "—"}
          unit="%"
          color={overall ? getWinrateColor(overall.win_rate) : undefined}
          sub={overall ? `${overall.win}-${overall.loss}-${overall.draw} · ${t("users.maps.gamesCount", { count: overall.total_games })}` : "—"}
        />
        <KPI
          label={t("users.maps.mostPlayed")}
          value={summary?.most_played ? `${summary.most_played.count}` : "—"}
          unit={t("users.maps.gamesUnit")}
          sub={summary?.most_played ? `${summary.most_played.map.name} · ${summary.most_played.map.gamemode?.name ?? ""}` : "—"}
        />
        <KPI
          label={t("users.maps.bestMap")}
          value={summary?.best ? `${(summary.best.win_rate * 100).toFixed(0)}` : "—"}
          unit="%"
          color={summary?.best ? getWinrateColor(summary.best.win_rate) : undefined}
          sub={summary?.best ? `${summary.best.map.name} · ${t("users.maps.gamesShort", { count: String(summary.best.count) })}` : "—"}
        />
        <KPI
          label={t("users.maps.weakest")}
          value={summary?.worst ? `${(summary.worst.win_rate * 100).toFixed(0)}` : "—"}
          unit="%"
          color={summary?.worst ? getWinrateColor(summary.worst.win_rate) : undefined}
          sub={summary?.worst ? `${summary.worst.map.name} · ${t("users.maps.gamesShort", { count: String(summary.worst.count) })}` : "—"}
        />
      </div>

      {/* Mode breakdown */}
      <CardSurface
        title={t("users.maps.byMode")}
        icon={<LayoutGrid size={15} />}
        subtitle={t("users.maps.byModeSubtitle", {
          modes: modeStats.length,
          games: allMaps.reduce((s, m) => s + m.count, 0)
        })}
      >
        <div className="aqt-mode-grid">
          {modeStats.map((b) => {
            const totalDecisive = b.win + b.loss;
            const wr = totalDecisive > 0 ? (b.win / totalDecisive) * 100 : 0;
            const active = modeFilter === b.mode;
            return (
              <button
                key={b.mode}
                type="button"
                onClick={() => setModeFilter(active ? null : b.mode)}
                aria-pressed={active}
                title={active ? t("users.maps.clearModeFilter") : t("users.maps.filterByMode", { mode: b.mode })}
                className={cn(
                  "aqt-mode-card w-full cursor-pointer text-left transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)]",
                  modeClass(b.mode)
                )}
                style={
                  active
                    ? { borderColor: "var(--aqt-teal)", background: "color-mix(in srgb, var(--aqt-teal) 10%, transparent)" }
                    : undefined
                }
              >
                <div className="aqt-l">{b.mode}</div>
                <div className="flex items-baseline justify-between gap-2">
                  <div className="aqt-display text-headline font-bold leading-none tabular-nums">{wr.toFixed(0)}%</div>
                  <div className="aqt-tnum text-ui text-[color:var(--aqt-fg-muted)]">
                    {b.win}-{b.loss}
                  </div>
                </div>
                <div className="aqt-bar">
                  <div className="aqt-fill" style={{ width: `${wr}%` }} />
                </div>
                <div className="aqt-tnum flex items-center justify-between text-label text-[color:var(--aqt-fg-dim)]">
                  <span>{t("users.maps.mapsCount", { count: b.maps.size })}</span>
                  <span>{t("users.maps.gamesCount", { count: b.games })}</span>
                </div>
              </button>
            );
          })}
        </div>
      </CardSurface>

      {/* Filter chips + controls */}
      <MapsFilters
        tournamentId={tournamentId}
        onTournamentIdChange={setTournamentId}
        tournamentOptions={tournamentOptions}
        tournamentsLoading={tournamentsQuery.isLoading}
        tournamentsError={tournamentsQuery.isError}
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
        <div className="grid grid-cols-[64px_1fr_1fr_minmax(0,1.2fr)_60px_50px] items-center gap-3.5 border-b border-[color:var(--aqt-border)] px-[18px] py-3 text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
          <div />
          <div>{t("users.maps.colMap")}</div>
          <div>{t("users.maps.colWinrate")}</div>
          <div>{t("common.heroes")}</div>
          <div className="text-right">{t("users.maps.colRecord")}</div>
          <div className="text-right">{t("users.maps.colGames")}</div>
        </div>
        {pageMaps.map((row) => (
          <MapRow key={row.map.id} row={row} />
        ))}
        {pageMaps.length === 0 ? (
          <div className="py-10 text-center text-[color:var(--aqt-fg-dim)]">
            {mapsQuery.isLoading ? t("common.loading") : t("users.maps.noMaps")}
          </div>
        ) : null}

        {/* Pagination footer */}
        {perPage !== -1 && totalCount > 0 ? (
          <DataPagination
            page={page}
            totalPages={pages}
            onPageChange={setPage}
            className="border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-[18px] py-3.5"
            summary={
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
