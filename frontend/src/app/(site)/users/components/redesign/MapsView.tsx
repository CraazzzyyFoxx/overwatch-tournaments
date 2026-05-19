"use client";

import React, { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";
import { cn } from "@/lib/utils";

import Image from "next/image";
import userService from "@/services/user.service";
import { UserMapRead, UserMapsSummary } from "@/types/user.types";
import { CardSurface } from "@/app/(site)/users/components/redesign/atoms";
import HeroImage from "@/app/(site)/users/components/redesign/HeroImage";
import { getWinrateColor } from "@/utils/colors";

interface Props {
  userId: number;
}

const MODE_ORDER = ["Control", "Escort", "Hybrid", "Flashpoint", "Push", "Assault"] as const;

const MapsView = ({ userId }: Props) => {
  const [modeFilter, setModeFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [debouncedSearch] = useDebounce(search, 300);
  const [sort] = useState<"winrate" | "count" | "name">("winrate");
  const [order] = useState<"asc" | "desc">("desc");
  const [minCount, setMinCount] = useState(1);

  const mapsQuery = useQuery({
    queryKey: ["user-maps-redesign", userId, debouncedSearch, minCount],
    queryFn: () =>
      userService.getUserMaps(userId, {
        page: 1,
        perPage: -1,
        sort,
        order,
        query: debouncedSearch.trim(),
        minCount
      }),
    staleTime: 60_000
  });

  const summaryQuery = useQuery({
    queryKey: ["user-maps-summary-redesign", userId, debouncedSearch, minCount],
    queryFn: () => userService.getUserMapsSummary(userId, { query: debouncedSearch.trim(), minCount }),
    staleTime: 60_000
  });

  const summary = summaryQuery.data as UserMapsSummary | undefined;
  const allMaps = mapsQuery.data?.results ?? [];

  // Aggregate by gamemode
  const modeStats = useMemo(() => {
    const buckets = new Map<string, { mode: string; maps: Set<number>; games: number; win: number; loss: number; draw: number }>();
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

  const filteredMaps = useMemo(() => {
    let rows = [...allMaps];
    if (modeFilter) {
      rows = rows.filter((r) => r.map.gamemode?.name === modeFilter);
    }
    rows.sort((a, b) => b.win_rate - a.win_rate);
    return rows;
  }, [allMaps, modeFilter]);

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

      {/* Filter chips */}
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
        <span
          className={cn("aqt-filter-chip", minCount === 3 && "active")}
          onClick={() => setMinCount(minCount === 3 ? 1 : 3)}
          role="button"
          tabIndex={0}
        >
          Min 3 games
        </span>
        <div className="filter-search relative ml-auto min-w-[200px] max-w-[300px] flex-1">
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
        <div className="border-b border-[color:var(--aqt-border)] px-[18px] py-3 grid grid-cols-[64px_1fr_1fr_80px_60px_50px] gap-3.5 items-center text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
          <div />
          <div>Map</div>
          <div>Winrate</div>
          <div>Heroes</div>
          <div className="text-right">Record</div>
          <div className="text-right">Games</div>
        </div>
        {filteredMaps.map((row) => {
          const wr = row.win_rate * 100;
          const wrCls = wr >= 60 ? "good" : wr <= 40 ? "bad" : "";
          return (
            <div key={row.map.id} className="aqt-map-row">
              <div className="aqt-map-thumb">
                {row.map.image_path ? (
                  <Image
                    src={row.map.image_path}
                    alt={row.map.name}
                    fill
                    sizes="56px"
                    className="object-cover"
                  />
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
              <span className="aqt-hero-strip">
                {(row.hero_stats ?? row.heroes ?? []).slice(0, 4).map((h, idx) => (
                  <HeroImage
                    key={`${row.map.id}-${h.hero.id}-${idx}`}
                    hero={h.hero}
                    size="sm"
                  />
                ))}
              </span>
              <span className="aqt-mono text-right text-[12.5px] font-semibold text-[color:var(--aqt-fg-muted)]">
                {row.win}-{row.loss}-{row.draw}
              </span>
              <span className="aqt-mono text-right text-[13px] font-semibold">{row.count}</span>
            </div>
          );
        })}
        {filteredMaps.length === 0 ? (
          <div className="py-10 text-center text-[color:var(--aqt-fg-dim)]">
            {mapsQuery.isLoading ? "Loading…" : "No maps match the filters"}
          </div>
        ) : null}
      </CardSurface>
    </div>
  );
};

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
