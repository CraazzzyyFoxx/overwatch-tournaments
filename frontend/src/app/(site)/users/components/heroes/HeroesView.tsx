"use client";

import React, { useMemo, useState } from "react";
import { Activity, Swords } from "lucide-react";
import { cn } from "@/lib/utils";
import { HeroWithUserStats } from "@/types/hero.types";
import type { UserMapRead } from "@/types/user.types";
import { LogStatsName } from "@/types/stats.types";
import { getHumanizedStats } from "@/utils/stats";
import {
  CardSurface,
  heroVariantFromRole,
  type AqtRoleKey
} from "@/app/(site)/users/components/shared/atoms";
import HeroImage from "@/components/hero/HeroImage";
import {
  computeDelta,
  formatDelta,
  formatPercent,
  formatSeconds,
  formatStatValue,
  getOverall,
  isRevertedStat
} from "@/app/(site)/users/components/heroes/utils";
import HeroRadar, { RADAR_STATS } from "@/app/(site)/users/components/heroes/HeroRadar";
import HeroSpotlight, {
  QUICK_CANDIDATES,
  QUICK_LABELS
} from "@/app/(site)/users/components/heroes/HeroSpotlight";
import HeroStatsTable, {
  type StatSortKey
} from "@/app/(site)/users/components/heroes/HeroStatsTable";
import MapsForHero from "@/app/(site)/users/components/heroes/MapsForHero";

interface Props {
  heroes: HeroWithUserStats[];
  filterSlot?: React.ReactNode;
  /** User maps (with per-hero stats) — powers the "Maps for [Hero]" panel. */
  maps?: UserMapRead[];
}

const HeroesView = ({ heroes, filterSlot, maps }: Props) => {
  const safeHeroes = Array.isArray(heroes) ? heroes : [];

  const items = useMemo(() => {
    return safeHeroes
      .map((h) => ({
        hero: h,
        playtime: getOverall(h, LogStatsName.HeroTimePlayed)
      }))
      .sort((a, b) => b.playtime - a.playtime);
  }, [safeHeroes]);

  const totalSeconds = items.reduce((sum, i) => sum + i.playtime, 0);
  const enriched = items.map((i) => ({
    ...i,
    share: totalSeconds > 0 ? i.playtime / totalSeconds : 0
  }));

  const [selectedId, setSelectedId] = useState<number>(enriched[0]?.hero.hero.id ?? 0);
  const [search, setSearch] = useState("");
  const [insightsMode, setInsightsMode] = useState<"highlights" | "all">("highlights");
  const [statSort, setStatSort] = useState<StatSortKey>("delta");
  const [statSearch, setStatSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return enriched;
    return enriched.filter((i) => i.hero.hero.name.toLowerCase().includes(q));
  }, [enriched, search]);

  const selected = useMemo(() => enriched.find((i) => i.hero.hero.id === selectedId) ?? enriched[0], [enriched, selectedId]);

  // Build radar data for selected hero (you vs global)
  const radarData = useMemo(() => {
    if (!selected) return null;
    const points = RADAR_STATS.map((statName) => {
      const stat = selected.hero.stats.find((s) => s.name === statName);
      if (!stat || !Number.isFinite(stat.avg_10) || !Number.isFinite(stat.avg_10_all)) {
        return { stat: statName, you: 0, global: 0 };
      }
      // Normalize: scale relative to max(you, global)
      const max = Math.max(stat.avg_10, stat.avg_10_all, 1);
      let you = stat.avg_10 / max;
      let global = stat.avg_10_all / max;
      if (isRevertedStat(statName)) {
        you = 1 - you;
        global = 1 - global;
      }
      return { stat: statName, you, global };
    });
    return points;
  }, [selected]);

  // Insights rows
  const insightsRows = useMemo(() => {
    if (!selected) return [];
    return selected.hero.stats
      .filter((s) => s.name !== LogStatsName.HeroTimePlayed)
      .filter((s) => Number.isFinite(s.avg_10) && Number.isFinite(s.avg_10_all) && s.avg_10_all > 0)
      .map((s) => {
        const reversed = isRevertedStat(s.name);
        const delta = computeDelta(s.avg_10, s.avg_10_all, reversed) ?? 0;
        return {
          name: s.name,
          label: getHumanizedStats(s.name),
          value: formatStatValue(s.name, s.avg_10),
          delta
        };
      })
      .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      .slice(0, 8);
  }, [selected]);

  // Spotlight quick-stats (Winrate / KDA / Dmg10 …) with delta vs global.
  const quickStats = useMemo(() => {
    if (!selected) return [];
    const out: { name: LogStatsName; label: string; value: string; delta: number | null }[] = [];
    for (const name of QUICK_CANDIDATES) {
      const stat = selected.hero.stats.find((s) => s.name === name);
      if (!stat || !Number.isFinite(stat.avg_10)) continue;
      const reversed = isRevertedStat(name);
      const delta = computeDelta(stat.avg_10, stat.avg_10_all, reversed);
      const value =
        name === LogStatsName.Winrate
          ? stat.avg_10 <= 1
            ? formatPercent(stat.avg_10, 0)
            : `${stat.avg_10.toFixed(0)}%`
          : formatStatValue(name, stat.avg_10);
      out.push({ name, label: QUICK_LABELS[name] ?? getHumanizedStats(name), value, delta });
      if (out.length === 3) break;
    }
    return out;
  }, [selected]);

  // Full per-stat comparison table (All stats mode).
  const allStatsRows = useMemo(() => {
    if (!selected) return [];
    const q = statSearch.trim().toLowerCase();
    let rows = selected.hero.stats
      .filter((s) => s.name !== LogStatsName.HeroTimePlayed)
      .map((s) => {
        const reversed = isRevertedStat(s.name);
        const delta = computeDelta(s.avg_10, s.avg_10_all, reversed);
        const isRecord =
          s.best_all != null &&
          Number.isFinite(s.best?.value) &&
          Number.isFinite(s.best_all.value) &&
          s.best.value === s.best_all.value;
        return {
          name: s.name,
          label: getHumanizedStats(s.name),
          overall: s.overall,
          bestYou: s.best?.value,
          avg10: s.avg_10,
          delta,
          bestAll: s.best_all?.value ?? null,
          global10: s.avg_10_all,
          isRecord
        };
      });
    if (q) rows = rows.filter((r) => r.label.toLowerCase().includes(q));
    rows.sort((a, b) => {
      if (statSort === "name") return a.label.localeCompare(b.label);
      if (statSort === "overall") return (b.overall ?? 0) - (a.overall ?? 0);
      if (statSort === "avg10") return (b.avg10 ?? 0) - (a.avg10 ?? 0);
      return Math.abs(b.delta ?? 0) - Math.abs(a.delta ?? 0);
    });
    return rows;
  }, [selected, statSearch, statSort]);

  // Maps the selected hero was played on, with the user's record on each.
  const heroMaps = useMemo(() => {
    if (!selected || !maps || maps.length === 0) return [];
    const heroId = selected.hero.hero.id;
    const rows = maps
      .map((m) => {
        const hs = (m.hero_stats ?? []).find((h) => h.hero.id === heroId);
        return hs ? { id: m.map.id, name: m.map.name, mode: m.map.gamemode?.name ?? "—", winRate: hs.win_rate, win: hs.win, loss: hs.loss } : null;
      })
      .filter((r): r is NonNullable<typeof r> => r !== null);
    rows.sort((a, b) => b.winRate - a.winRate || b.win + b.loss - (a.win + a.loss));
    return rows.slice(0, 6);
  }, [selected, maps]);

  const mostEffective = useMemo(() => {
    let best: typeof enriched[0] | null = null;
    let bestScore = -Infinity;
    for (const item of enriched) {
      if (item.playtime < 30 * 60) continue;
      let positive = 0;
      let total = 0;
      for (const stat of item.hero.stats) {
        if (stat.name === LogStatsName.HeroTimePlayed) continue;
        if (!Number.isFinite(stat.avg_10) || !Number.isFinite(stat.avg_10_all) || stat.avg_10_all <= 0) continue;
        total++;
        const reversed = isRevertedStat(stat.name);
        if ((reversed ? stat.avg_10 < stat.avg_10_all : stat.avg_10 > stat.avg_10_all)) positive++;
      }
      if (total > 0 && positive > bestScore) {
        bestScore = positive;
        best = item;
      }
    }
    return best;
  }, [enriched]);

  if (!selected) {
    return (
      <div className="aqt-player">
        <CardSurface>
          <div className="py-10 text-center text-[color:var(--aqt-fg-dim)]">No hero stats available yet.</div>
        </CardSurface>
      </div>
    );
  }

  const heroVariant = heroVariantFromRole(selected.hero.hero.type ?? selected.hero.hero.role) as AqtRoleKey;

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      {filterSlot ? <div className="flex justify-end">{filterSlot}</div> : null}

      {/* Top KPI row */}
      <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-3">
        <CardSurface>
          <div className="flex items-center gap-3.5">
            <div className="relative h-[74px] w-[74px]">
              <svg viewBox="0 0 100 100" className="h-full w-full">
                <circle cx="50" cy="50" r="42" fill="none" stroke="hsl(0 0% 100% / 0.05)" strokeWidth="8" />
                <circle
                  cx="50"
                  cy="50"
                  r="42"
                  fill="none"
                  stroke="var(--aqt-teal)"
                  strokeWidth="8"
                  strokeDasharray="264"
                  strokeDashoffset={264 - Math.min(264, 264 * (items.length / 35))}
                  strokeLinecap="round"
                  transform="rotate(-90 50 50)"
                />
              </svg>
            </div>
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Hero pool</div>
              <div className="aqt-display text-[26px] font-bold leading-[1.1]">
                {items.length}{" "}
                <span className="aqt-mono text-[13px] text-[color:var(--aqt-fg-muted)]">heroes</span>
              </div>
              <div className="aqt-mono text-[11px] text-[color:var(--aqt-emerald)]">Across roles</div>
            </div>
          </div>
        </CardSurface>

        <CardSurface>
          <div className="flex items-center gap-3.5">
            <div className="aqt-display text-[46px] font-bold leading-none" style={{ color: "var(--aqt-amber)" }}>
              {Math.floor(totalSeconds / 3600)}
              <span className="aqt-mono text-[16px] text-[color:var(--aqt-fg-muted)]">h</span>
            </div>
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Total playtime</div>
              <div className="aqt-mono text-[13px]">{formatSeconds(totalSeconds)}</div>
              <div className="aqt-mono text-[11px] text-[color:var(--aqt-fg-dim)]">{items.length} heroes</div>
            </div>
          </div>
        </CardSurface>

        <CardSurface>
          <div className="flex items-center gap-3.5">
            {mostEffective ? (
              <HeroImage hero={mostEffective.hero.hero} size="lg" />
            ) : (
              <span className="aqt-hero-av lg damage">—</span>
            )}
            <div>
              <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Most effective</div>
              <div className="aqt-display text-[22px] font-bold leading-[1.1]">
                {mostEffective?.hero.hero.name ?? "—"}
              </div>
              <div className="aqt-mono text-[11px] text-[color:var(--aqt-emerald)]">
                {mostEffective ? formatSeconds(mostEffective.playtime) : "—"}
              </div>
            </div>
          </div>
        </CardSurface>
      </div>

      {/* Main layout: list + detail */}
      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-[340px_1fr]">
        <CardSurface
          flush
          title="Hero pool"
          icon={<Swords size={15} />}
          subtitle="tracked > 60s"
          headerClassName="flex-col items-stretch gap-2.5"
        >
          <div className="border-b border-[color:var(--aqt-border)] px-3.5 py-2.5">
            <div className="relative">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
              <input
                placeholder="Search heroes…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 py-1.5 pl-8 text-[12.5px] text-[color:var(--aqt-fg)] outline-none"
              />
            </div>
          </div>
          <div className="max-h-[680px] overflow-y-auto">
            {filtered.map((item) => {
              const isActive = item.hero.hero.id === selected?.hero.hero.id;
              return (
                <div
                  key={item.hero.hero.id}
                  className={cn(
                    "grid cursor-pointer grid-cols-[32px_1fr_auto] items-center gap-2.5 border-b border-[color:var(--aqt-border)] px-3.5 py-2.5 transition-colors hover:bg-[hsl(0_0%_100%/0.025)]",
                    isActive && "border-l-2 border-l-[color:var(--aqt-teal)] bg-[hsl(174_72%_46%/0.08)] pl-3"
                  )}
                  onClick={() => setSelectedId(item.hero.hero.id)}
                >
                  <HeroImage hero={item.hero.hero} size="md" />
                  <div className="flex flex-col gap-0.5 min-w-0">
                    <div className="truncate text-[13px] font-semibold">{item.hero.hero.name}</div>
                    <div className="flex items-center gap-1.5 text-[11px] text-[color:var(--aqt-fg-dim)]">
                      <span className="capitalize">{item.hero.hero.type ?? item.hero.hero.role}</span>
                      <span>· {(item.share * 100).toFixed(0)}%</span>
                    </div>
                    <div className="mt-1 h-1 w-full overflow-hidden rounded-sm bg-[hsl(0_0%_100%/0.04)]">
                      <div className="h-full rounded-sm bg-[color:var(--aqt-teal)]" style={{ width: `${item.share * 100}%` }} />
                    </div>
                  </div>
                  <span className="aqt-mono text-right text-[11px] text-[color:var(--aqt-fg-muted)]">
                    {formatSeconds(item.playtime)}
                  </span>
                </div>
              );
            })}
            {filtered.length === 0 ? (
              <div className="p-6 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">No heroes match search</div>
            ) : null}
          </div>
        </CardSurface>

        <div className="flex flex-col gap-3.5">
          {/* Spotlight */}
          <HeroSpotlight selected={selected} heroVariant={heroVariant} quickStats={quickStats} />

          {/* Radar + insights */}
          <CardSurface
            title="Insights"
            icon={<Activity size={15} />}
            subtitle={`${selected.hero.hero.name} · vs global avg/10`}
            action={
              <div className="aqt-filters !mb-0">
                <span
                  className={cn("aqt-filter-chip", insightsMode === "highlights" && "active")}
                  role="button"
                  tabIndex={0}
                  onClick={() => setInsightsMode("highlights")}
                >
                  Highlights
                </span>
                <span
                  className={cn("aqt-filter-chip", insightsMode === "all" && "active")}
                  role="button"
                  tabIndex={0}
                  onClick={() => setInsightsMode("all")}
                >
                  All stats
                  <span className="aqt-count">{allStatsRows.length}</span>
                </span>
              </div>
            }
          >
            {insightsMode === "highlights" ? (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-[280px_1fr]">
              <HeroRadar radarData={radarData} />
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {insightsRows.map((row) => (
                  <div
                    key={row.name}
                    className="flex items-center justify-between gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] px-3 py-2.5"
                  >
                    <span className="text-[11px] text-[color:var(--aqt-fg-muted)]">{row.label}</span>
                    <span className="aqt-mono text-[13px] font-semibold text-[color:var(--aqt-fg)]">{row.value}</span>
                    <span
                      className="aqt-mono text-[10.5px] font-bold"
                      style={{ color: row.delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                    >
                      {formatDelta(row.delta)}
                    </span>
                  </div>
                ))}
                {insightsRows.length === 0 ? (
                  <div className="col-span-2 py-6 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">
                    Not enough data for comparisons
                  </div>
                ) : null}
              </div>
            </div>
            ) : (
              <HeroStatsTable
                rows={allStatsRows}
                sort={statSort}
                onSortChange={setStatSort}
                search={statSearch}
                onSearchChange={setStatSearch}
              />
            )}
          </CardSurface>

          {/* Maps the selected hero was played on */}
          <MapsForHero heroName={selected.hero.hero.name} heroMaps={heroMaps} />
        </div>
      </div>
    </div>
  );
};

export default HeroesView;
