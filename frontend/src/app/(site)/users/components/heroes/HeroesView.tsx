"use client";

import React, { useMemo, useState } from "react";
import { Activity } from "lucide-react";
import { cn } from "@/lib/utils";
import { HeroWithUserStats } from "@/types/hero.types";
import type { UserMapRead } from "@/types/user.types";
import { LogStatsName } from "@/types/stats.types";
import { getHumanizedStats } from "@/utils/stats";
import {
  CardSurface,
  heroVariantFromRole,
  normalizeRole,
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
import HeroRadar, { RADAR_STATS, type RadarPoint } from "@/app/(site)/users/components/heroes/HeroRadar";
import HeroSpotlight, {
  QUICK_CANDIDATES,
  QUICK_LABELS
} from "@/app/(site)/users/components/heroes/HeroSpotlight";
import HeroStatsTable, {
  type StatSortKey
} from "@/app/(site)/users/components/heroes/HeroStatsTable";
import MapsForHero from "@/app/(site)/users/components/heroes/MapsForHero";
import HeroRail, { type HeroRow } from "@/app/(site)/users/components/heroes/HeroRail";
import HeroBestGames from "@/app/(site)/users/components/heroes/HeroBestGames";

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
  const [insightsMode, setInsightsMode] = useState<"highlights" | "all">("highlights");
  const [statSort, setStatSort] = useState<StatSortKey>("delta");
  const [statSearch, setStatSearch] = useState("");
  const [radarStats, setRadarStats] = useState<LogStatsName[]>(RADAR_STATS);

  const selected = useMemo(() => enriched.find((i) => i.hero.hero.id === selectedId) ?? enriched[0], [enriched, selectedId]);

  // Cross-hero overview rows (one per tracked hero) for the leaderboard table.
  const overviewRows = useMemo<HeroRow[]>(() => {
    const avg = (stats: HeroWithUserStats["stats"], name: LogStatsName) => {
      const v = stats.find((s) => s.name === name)?.avg_10;
      return v != null && Number.isFinite(v) ? v : null;
    };
    return enriched.map((it) => {
      const stats = it.hero.stats;
      const wr = avg(stats, LogStatsName.Winrate);
      let positive = 0;
      let total = 0;
      for (const s of stats) {
        if (s.name === LogStatsName.HeroTimePlayed) continue;
        if (!Number.isFinite(s.avg_10) || !Number.isFinite(s.avg_10_all) || s.avg_10_all <= 0) continue;
        total++;
        if (isRevertedStat(s.name) ? s.avg_10 < s.avg_10_all : s.avg_10 > s.avg_10_all) positive++;
      }
      return {
        id: it.hero.hero.id,
        hero: it.hero.hero,
        role: it.hero.hero.type ?? it.hero.hero.role,
        playtime: it.playtime,
        share: it.share,
        winratePct: wr == null ? null : wr <= 1 ? wr * 100 : wr,
        kda: avg(stats, LogStatsName.KDA),
        dmg10: avg(stats, LogStatsName.HeroDamageDealt),
        impact: total > 0 ? positive / total : 0
      };
    });
  }, [enriched]);

  // Role split for the summary strip (tank / damage / support counts).
  const roleSplit = useMemo(() => {
    const acc = { tank: 0, damage: 0, support: 0 };
    for (const it of enriched) {
      const r = normalizeRole(it.hero.hero.type ?? it.hero.hero.role);
      if (r) acc[r] += 1;
    }
    return acc;
  }, [enriched]);

  // Build radar data for the selected hero (you vs global) over the chosen
  // axes. Stats the hero has no data for are dropped (no phantom 0-axis).
  const radarData = useMemo(() => {
    if (!selected) return null;
    const points = radarStats
      .map((statName) => {
        const stat = selected.hero.stats.find((s) => s.name === statName);
        if (!stat || !Number.isFinite(stat.avg_10) || !Number.isFinite(stat.avg_10_all) || stat.avg_10_all <= 0) {
          return null;
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
      })
      .filter((p): p is RadarPoint => p !== null);
    return points.length >= 3 ? points : null;
  }, [selected, radarStats]);

  // Stats that can be plotted on the radar for the selected hero (have data).
  const radarCandidates = useMemo(() => {
    if (!selected) return [] as LogStatsName[];
    return selected.hero.stats
      .filter((s) => s.name !== LogStatsName.HeroTimePlayed)
      .filter((s) => Number.isFinite(s.avg_10) && Number.isFinite(s.avg_10_all) && s.avg_10_all > 0)
      .map((s) => s.name);
  }, [selected]);

  const toggleRadarStat = (name: LogStatsName) => {
    setRadarStats((prev) => {
      if (prev.includes(name)) {
        // Keep at least 3 axes so the radar stays a polygon.
        return prev.length <= 3 ? prev : prev.filter((s) => s !== name);
      }
      // Cap at 8 axes to keep the chart legible.
      return prev.length >= 8 ? prev : [...prev, name];
    });
  };

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
    return rows;
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

      {/* Summary strip (one compact row; no duplicate "Hero pool") */}
      <div className="aqt-card-surface flex flex-wrap items-center gap-x-8 gap-y-3 px-[18px] py-3.5">
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Hero pool</div>
          <div className="aqt-display text-[22px] font-bold leading-[1.1]">
            {items.length} <span className="aqt-mono text-[13px] text-[color:var(--aqt-fg-muted)]">heroes</span>
          </div>
          <div className="aqt-mono text-[12px] text-[color:var(--aqt-fg-dim)]">
            {roleSplit.tank}T · {roleSplit.damage}D · {roleSplit.support}S
          </div>
        </div>
        <div>
          <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Total playtime</div>
          <div className="aqt-display text-[22px] font-bold leading-[1.1]" style={{ color: "var(--aqt-amber)" }}>
            {Math.floor(totalSeconds / 3600)}
            <span className="aqt-mono text-[13px] text-[color:var(--aqt-fg-muted)]">h</span>
          </div>
          <div className="aqt-mono text-[12px] text-[color:var(--aqt-fg-dim)]">{formatSeconds(totalSeconds)}</div>
        </div>
        {mostEffective ? (
          <div className="flex items-center gap-2.5">
            <HeroImage hero={mostEffective.hero.hero} size="md" />
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">Most effective</div>
              <div className="aqt-display text-[18px] font-bold leading-[1.1]">{mostEffective.hero.hero.name}</div>
              <div className="aqt-mono text-[12px] text-[color:var(--aqt-emerald)]">{formatSeconds(mostEffective.playtime)}</div>
            </div>
          </div>
        ) : null}
      </div>

      {/* Sticky hero rail (cross-hero compare) + detail, side by side so
          switching heroes never requires a long scroll up/down. */}
      <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-[340px_1fr] xl:items-start">
        <HeroRail rows={overviewRows} selectedId={selected.hero.hero.id} onSelect={setSelectedId} />

        <div className="flex min-w-0 flex-col gap-3.5">
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
              <div className="flex flex-col gap-2.5">
                <HeroRadar radarData={radarData} />
                {radarCandidates.length > 0 ? (
                  <div className="flex flex-col gap-1.5">
                    <span className="text-center text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
                      Radar axes · pick 3–8
                    </span>
                    <div className="flex flex-wrap justify-center gap-1.5">
                      {radarCandidates.map((name) => (
                        <span
                          key={name}
                          role="button"
                          tabIndex={0}
                          onClick={() => toggleRadarStat(name)}
                          className={cn("aqt-filter-chip", radarStats.includes(name) && "active")}
                          title={getHumanizedStats(name)}
                        >
                          {getHumanizedStats(name)}
                        </span>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {insightsRows.map((row) => (
                  <div
                    key={row.name}
                    className="flex items-center justify-between gap-2 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] px-3 py-2.5"
                  >
                    <span className="text-[12px] text-[color:var(--aqt-fg-muted)]">{row.label}</span>
                    <span className="aqt-mono text-[14px] font-semibold text-[color:var(--aqt-fg)]">{row.value}</span>
                    <span
                      className="aqt-mono text-[11.5px] font-bold"
                      style={{ color: row.delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                    >
                      {formatDelta(row.delta)}
                    </span>
                  </div>
                ))}
                {insightsRows.length === 0 ? (
                  <div className="col-span-2 py-6 text-center text-[13px] text-[color:var(--aqt-fg-dim)]">
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

          {/* Career-best single-game performances for the selected hero */}
          <HeroBestGames hero={selected.hero} />

          {/* Maps the selected hero was played on (best → worst) */}
          <MapsForHero heroName={selected.hero.hero.name} heroMaps={heroMaps} />
        </div>
      </div>
    </div>
  );
};

export default HeroesView;
