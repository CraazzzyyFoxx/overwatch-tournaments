"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";
import { cn } from "@/lib/utils";

import Image from "next/image";
import userService from "@/services/user.service";
import { UserMapsSummary } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/redesign/atoms";
import SearchableImageSelect, {
  type SearchableImageOption
} from "@/app/(site)/users/compare/components/SearchableImageSelect";
import HeroImage from "@/components/hero/HeroImage";
import HeroStatsPopover from "@/components/hero/HeroStatsPopover";
import { AvatarStack } from "@/components/ui/avatar";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { getWinrateColor } from "@/utils/colors";

interface Props {
  userId: number;
}

const MODE_ORDER = ["Control", "Escort", "Hybrid", "Flashpoint", "Push", "Assault"] as const;

type SortKey = "winrate" | "count" | "name";
type OrderKey = "asc" | "desc";

const MIN_COUNT_OPTIONS = [1, 3, 5, 10];
const PER_PAGE_OPTIONS = [15, 30, -1];
const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "winrate", label: "Winrate" },
  { value: "count", label: "Games" },
  { value: "name", label: "Name" }
];

const AqtSelect = ({
  value,
  onChange,
  options,
  title,
  width = "w-[150px]"
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  title?: string;
  width?: string;
}) => (
  <Select value={value} onValueChange={onChange}>
    <SelectTrigger
      title={title}
      className={cn(
        "aqt-mono h-8 shadow-none border-white/[0.07] bg-white/[0.02] text-[12px] text-white/80 hover:border-white/[0.13] hover:bg-white/[0.04] focus:ring-1 focus:ring-white/[0.15] focus:ring-offset-0",
        width
      )}
    >
      <SelectValue />
    </SelectTrigger>
    <SelectContent className="max-h-[min(var(--radix-select-content-available-height),20rem)]">
      {options.map((o) => (
        <SelectItem key={o.value} value={o.value}>
          {o.label}
        </SelectItem>
      ))}
    </SelectContent>
  </Select>
);

const MapsView = ({ userId }: Props) => {
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
    queryKey: ["user-maps-redesign", userId, debouncedSearch, minCount, tournamentId],
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
    queryKey: ["user-maps-summary-redesign", userId, debouncedSearch, minCount, tournamentId],
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
      const mode = row.map.gamemode?.name ?? "Unknown";
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
  }, [allMaps]);

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
          label="Overall winrate"
          value={overall ? `${(overall.win_rate * 100).toFixed(1)}` : "—"}
          unit="%"
          color={overall ? getWinrateColor(overall.win_rate) : undefined}
          sub={overall ? `${overall.win}-${overall.loss}-${overall.draw} · ${overall.total_games} games` : "—"}
        />
        <KPI
          label="Most played"
          value={summary?.most_played ? `${summary.most_played.count}` : "—"}
          unit=" games"
          sub={summary?.most_played ? `${summary.most_played.map.name} · ${summary.most_played.map.gamemode?.name ?? ""}` : "—"}
        />
        <KPI
          label="Best map"
          value={summary?.best ? `${(summary.best.win_rate * 100).toFixed(0)}` : "—"}
          unit="%"
          color={summary?.best ? getWinrateColor(summary.best.win_rate) : undefined}
          sub={summary?.best ? `${summary.best.map.name} · ${summary.best.count} g` : "—"}
        />
        <KPI
          label="Weakest"
          value={summary?.worst ? `${(summary.worst.win_rate * 100).toFixed(0)}` : "—"}
          unit="%"
          color={summary?.worst ? getWinrateColor(summary.worst.win_rate) : undefined}
          sub={summary?.worst ? `${summary.worst.map.name} · ${summary.worst.count} g` : "—"}
        />
      </div>

      {/* Mode breakdown */}
      <CardSurface
        title="By mode"
        icon={<span>◫</span>}
        subtitle={`Winrate by game mode · ${modeStats.length} modes · ${allMaps.reduce((s, m) => s + m.count, 0)} games`}
      >
        <div className="aqt-mode-grid">
          {modeStats.map((b) => {
            const totalDecisive = b.win + b.loss;
            const wr = totalDecisive > 0 ? (b.win / totalDecisive) * 100 : 0;
            return (
              <div key={b.mode} className={cn("aqt-mode-card", modeClass(b.mode))}>
                <div className="aqt-l">{b.mode}</div>
                <div className="flex items-baseline justify-between gap-2">
                  <div className="aqt-display text-[30px] font-bold leading-none">{wr.toFixed(0)}%</div>
                  <div className="aqt-mono text-[14px] text-[color:var(--aqt-fg-muted)]">
                    {b.win}-{b.loss}
                  </div>
                </div>
                <div className="aqt-bar">
                  <div className="aqt-fill" style={{ width: `${wr}%` }} />
                </div>
                <div className="aqt-mono flex items-center justify-between text-[11px] text-[color:var(--aqt-fg-dim)]">
                  <span>{b.maps.size} maps</span>
                  <span>{b.games} games</span>
                </div>
              </div>
            );
          })}
        </div>
      </CardSurface>

      {/* Filter chips + controls */}
      <div className="aqt-filters">
        <span
          className={cn("aqt-filter-chip", modeFilter === null && "active")}
          onClick={() => setModeFilter(null)}
          role="button"
          tabIndex={0}
        >
          All modes
        </span>
        {modeStats.map((b) => (
          <span
            key={b.mode}
            className={cn("aqt-filter-chip", modeFilter === b.mode && "active")}
            onClick={() => setModeFilter(b.mode)}
            role="button"
            tabIndex={0}
          >
            {b.mode}
          </span>
        ))}
        <span className="aqt-filter-divider" />

        <div className="w-48">
          <SearchableImageSelect
            value={tournamentId ? String(tournamentId) : undefined}
            onValueChange={(val) => setTournamentId(val ? Number(val) : undefined)}
            options={tournamentOptions}
            placeholder="All tournaments"
            searchPlaceholder="Search tournament…"
            isLoading={tournamentsQuery.isLoading}
            disabled={tournamentsQuery.isLoading || tournamentsQuery.isError}
          />
        </div>

        <AqtSelect
          title="Minimum games"
          value={String(minCount)}
          onChange={(v) => setMinCount(Number(v))}
          options={MIN_COUNT_OPTIONS.map((n) => ({ value: String(n), label: `Min ${n} games` }))}
        />
        <AqtSelect
          title="Rows per page"
          value={String(perPage)}
          onChange={(v) => setPerPage(Number(v))}
          options={PER_PAGE_OPTIONS.map((n) => ({ value: String(n), label: n === -1 ? "Rows: All" : `Rows: ${n}` }))}
        />
        <AqtSelect
          title="Sort by"
          value={sort}
          onChange={(v) => setSort(v as SortKey)}
          options={SORT_OPTIONS.map((o) => ({ value: o.value, label: `Sort: ${o.label}` }))}
        />
        <button
          type="button"
          onClick={() => setOrder((o) => (o === "asc" ? "desc" : "asc"))}
          title={order === "asc" ? "Ascending" : "Descending"}
          className="aqt-mono inline-flex h-8 w-8 items-center justify-center rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[13px] text-[color:var(--aqt-fg-muted)] transition-colors hover:text-[color:var(--aqt-fg)]"
        >
          {order === "asc" ? "↑" : "↓"}
        </button>

        <div className="filter-search relative ml-auto min-w-[180px] max-w-[300px] flex-1">
          <input
            placeholder="Search maps…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] px-3 py-1.5 pl-8 text-[13px] outline-none"
          />
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
        </div>
      </div>

      {/* Map rows */}
      <CardSurface flush>
        <div className="grid grid-cols-[64px_1fr_1fr_minmax(0,1.2fr)_60px_50px] items-center gap-3.5 border-b border-[color:var(--aqt-border)] px-[18px] py-3 text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          <div />
          <div>Map</div>
          <div>Winrate</div>
          <div>Heroes</div>
          <div className="text-right">Record</div>
          <div className="text-right">Games</div>
        </div>
        {pageMaps.map((row) => {
          const wr = row.win_rate * 100;
          const wrCls = wr >= 60 ? "good" : wr <= 40 ? "bad" : "";
          const heroStats = row.hero_stats ?? [];
          return (
            <div key={row.map.id} className="aqt-map-row" style={{ gridTemplateColumns: "64px 1fr 1fr minmax(0,1.2fr) 60px 50px" }}>
              <div className="aqt-map-thumb">
                {row.map.image_path ? (
                  <Image src={row.map.image_path} alt={row.map.name} fill sizes="56px" className="object-cover" />
                ) : (
                  <span>{row.map.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase()}</span>
                )}
              </div>
              <div className="flex flex-col leading-tight">
                <div className="text-[13.5px] font-semibold text-[color:var(--aqt-fg)]">{row.map.name}</div>
                <div className="aqt-mono text-[10.5px] uppercase tracking-[0.06em] text-[color:var(--aqt-fg-dim)]">
                  {row.map.gamemode?.name ?? "—"}
                </div>
              </div>
              <div className="aqt-wr-bar">
                <div className="aqt-track">
                  <div className="aqt-fill" style={{ width: `${wr}%` }} />
                </div>
                <span className={cn("aqt-num", wrCls)}>{wr.toFixed(0)}%</span>
              </div>
              {heroStats.length > 0 ? (
                <AvatarStack max={8} size={26}>
                  {heroStats.map((hs) => (
                    <HeroImage
                      key={`${row.map.id}:${hs.hero.id}`}
                      hero={hs.hero}
                      size="sm"
                      popover={<HeroStatsPopover stats={hs} />}
                    />
                  ))}
                </AvatarStack>
              ) : (
                <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-faint)]">—</span>
              )}
              <span className="aqt-mono text-right text-[12.5px] font-semibold text-[color:var(--aqt-fg-muted)]">
                {row.win}-{row.loss}-{row.draw}
              </span>
              <span className="aqt-mono text-right text-[13px] font-semibold">{row.count}</span>
            </div>
          );
        })}
        {pageMaps.length === 0 ? (
          <div className="py-10 text-center text-[color:var(--aqt-fg-dim)]">
            {mapsQuery.isLoading ? "Loading…" : "No maps match the filters"}
          </div>
        ) : null}

        {/* Pagination footer */}
        {perPage !== -1 && totalCount > 0 ? (
          <div className="flex items-center justify-between border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.012)] px-[18px] py-3.5">
            <span className="aqt-mono text-[12px] text-[color:var(--aqt-fg-dim)]">
              Showing {(page - 1) * perPage + 1}–{Math.min(page * perPage, totalCount)} of {totalCount}
            </span>
            <div className="flex gap-1">
              <PageBtn disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>‹</PageBtn>
              {Array.from({ length: Math.min(3, pages) }, (_, i) => i + 1).map((n) => (
                <PageBtn key={n} active={n === page} onClick={() => setPage(n)}>{n}</PageBtn>
              ))}
              {pages > 3 ? (
                <>
                  {page > 4 ? <span className="aqt-mono px-2 text-[color:var(--aqt-fg-faint)]">…</span> : null}
                  <PageBtn active={page === pages} onClick={() => setPage(pages)}>{pages}</PageBtn>
                </>
              ) : null}
              <PageBtn disabled={page >= pages} onClick={() => setPage((p) => Math.min(pages, p + 1))}>›</PageBtn>
            </div>
          </div>
        ) : null}
      </CardSurface>
    </div>
  );
};

const PageBtn = ({
  active,
  disabled,
  onClick,
  children
}: {
  active?: boolean;
  disabled?: boolean;
  onClick?: () => void;
  children: React.ReactNode;
}) => (
  <button
    onClick={onClick}
    disabled={disabled}
    className={cn(
      "aqt-mono inline-flex h-8 min-w-[32px] items-center justify-center rounded-[6px] border px-2 text-[12px] transition-colors",
      active
        ? "border-[hsl(174_72%_46%/0.3)] bg-[hsl(174_72%_46%/0.12)] text-[color:var(--aqt-teal)]"
        : "border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.02)] text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]",
      disabled && "cursor-not-allowed opacity-40"
    )}
  >
    {children}
  </button>
);

const KPI = ({ label, value, unit, color, sub }: { label: string; value: string; unit?: string; color?: string; sub?: string }) => (
  <CardSurface>
    <div className="flex flex-col gap-1">
      <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{label}</div>
      <div className="aqt-display text-[38px] font-bold leading-[1.1]" style={{ color: color ?? "var(--aqt-fg)" }}>
        {value}
        {unit ? <span className="text-[22px] text-[color:var(--aqt-fg-faint)]">{unit}</span> : null}
      </div>
      {sub ? <div className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">{sub}</div> : null}
    </div>
  </CardSurface>
);

export default MapsView;
