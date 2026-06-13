"use client";

import React, { useMemo, useState } from "react";
import { Activity, Map as MapIcon, Swords } from "lucide-react";
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

interface Props {
  heroes: HeroWithUserStats[];
  filterSlot?: React.ReactNode;
  /** User maps (with per-hero stats) — powers the "Maps for [Hero]" panel. */
  maps?: UserMapRead[];
}

type StatSortKey = "delta" | "overall" | "avg10" | "name";

// Quick-stats shown in the spotlight (first 3 present, in this order).
const QUICK_CANDIDATES: LogStatsName[] = [
  LogStatsName.Winrate,
  LogStatsName.KDA,
  LogStatsName.HeroDamageDealt,
  LogStatsName.Eliminations
];

const QUICK_LABELS: Partial<Record<LogStatsName, string>> = {
  [LogStatsName.Winrate]: "Winrate",
  [LogStatsName.KDA]: "KDA",
  [LogStatsName.HeroDamageDealt]: "Dmg/10",
  [LogStatsName.Eliminations]: "Elims/10"
};

const RADAR_STATS: LogStatsName[] = [
  LogStatsName.HeroDamageDealt,
  LogStatsName.Eliminations,
  LogStatsName.CriticalHits,
  LogStatsName.Deaths,
  LogStatsName.HealingDealt
];

const RADAR_LABELS: Record<string, string> = {
  [LogStatsName.HeroDamageDealt]: "DMG",
  [LogStatsName.Eliminations]: "ELIMS",
  [LogStatsName.CriticalHits]: "CRITS",
  [LogStatsName.Deaths]: "SURV",
  [LogStatsName.HealingDealt]: "HEAL"
};

const radarPolygon = (values: number[], radius = 100): string => {
  const n = values.length;
  return values
    .map((v, i) => {
      const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
      const r = Math.max(0, Math.min(1, v)) * radius;
      const x = Math.cos(angle) * r;
      const y = Math.sin(angle) * r;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
};

const radarSpoke = (i: number, n: number, radius = 100): { x: number; y: number } => {
  const angle = (Math.PI * 2 * i) / n - Math.PI / 2;
  return {
    x: Math.cos(angle) * radius,
    y: Math.sin(angle) * radius
  };
};

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
          <div
            className="relative grid grid-cols-[auto_1fr_auto] items-center gap-6 overflow-hidden rounded-xl border p-5"
            style={{
              background: `linear-gradient(135deg, hsl(${heroVariant === "tank" ? "210" : heroVariant === "support" ? "142" : "340"} 65% 50% / 0.18), hsl(${heroVariant === "tank" ? "210" : heroVariant === "support" ? "142" : "340"} 65% 50% / 0.04))`,
              borderColor: `hsl(${heroVariant === "tank" ? "210" : heroVariant === "support" ? "142" : "340"} 78% 60% / 0.25)`
            }}
          >
            <div className="absolute inset-0 pointer-events-none" style={{
              backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='80' height='92.4'%3E%3Cpolygon points='40,1 79,23.2 79,69.2 40,91.4 1,69.2 1,23.2' fill='none' stroke='white' stroke-width='0.8' opacity='0.05'/%3E%3C/svg%3E\")",
              backgroundSize: "80px 92.4px"
            }} />
            <div
              className="relative z-[1] h-24 w-24 overflow-hidden rounded-[14px] border"
              style={{
                borderColor: selected.hero.hero.color || `hsl(${heroVariant === "tank" ? "210" : heroVariant === "support" ? "142" : "340"} 50% 35%)`
              }}
            >
              <HeroImage hero={selected.hero.hero} size={96} rounded="lg" />
            </div>
            <div className="relative z-[1] flex flex-col gap-1.5">
              <div className="aqt-display text-[34px] font-bold uppercase leading-none tracking-[0.02em]">
                {selected.hero.hero.name}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <span
                  className="aqt-mono inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[11px] uppercase tracking-[0.06em]"
                  style={{ background: `var(--aqt-${heroVariant})`, color: "hsl(220 30% 8%)" }}
                >
                  {selected.hero.hero.type ?? selected.hero.hero.role}
                </span>
                <span className="aqt-mono text-[12px] text-[color:var(--aqt-fg-muted)]">
                  {formatSeconds(selected.playtime, { withSeconds: false })} played
                </span>
                <span
                  className="aqt-mono inline-flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_100%/0.06)] px-2 py-0.5 text-[11px]"
                >
                  ▎ {(selected.share * 100).toFixed(0)}% pool share
                </span>
              </div>
            </div>
            <div className="relative z-[1] flex flex-wrap justify-end gap-4">
              {quickStats.length > 0 ? (
                quickStats.map((qs) => <QuickStat key={qs.name} label={qs.label} value={qs.value} delta={qs.delta} />)
              ) : (
                <QuickStat label="Playtime share" value={`${(selected.share * 100).toFixed(0)}%`} delta={null} />
              )}
            </div>
          </div>

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
              <div className="flex flex-col items-center gap-2">
                {radarData ? (
                  <svg viewBox="-130 -130 260 260" width="240" height="240" className="block">
                    {[100, 75, 50, 25].map((r) => (
                      <polygon
                        key={r}
                        className="aqt-radar-grid"
                        points={radarPolygon([1, 1, 1, 1, 1].map(() => r / 100), 100)}
                      />
                    ))}
                    {radarData.map((_, i) => {
                      const p = radarSpoke(i, radarData.length, 100);
                      return <line key={i} className="aqt-radar-spoke" x1={0} y1={0} x2={p.x} y2={p.y} />;
                    })}
                    <polygon className="aqt-radar-global" points={radarPolygon(radarData.map((d) => d.global), 100)} />
                    <polygon className="aqt-radar-you" points={radarPolygon(radarData.map((d) => d.you), 100)} />
                    {radarData.map((d, i) => {
                      const p = radarSpoke(i, radarData.length, 116);
                      return (
                        <text
                          key={i}
                          className="aqt-radar-axis"
                          x={p.x}
                          y={p.y}
                          textAnchor={p.x < -2 ? "end" : p.x > 2 ? "start" : "middle"}
                          dominantBaseline="middle"
                        >
                          {RADAR_LABELS[d.stat] ?? d.stat}
                        </text>
                      );
                    })}
                  </svg>
                ) : null}
                <div className="flex gap-3.5 pt-1.5 text-[11px] text-[color:var(--aqt-fg-muted)]">
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--aqt-teal)" }} />
                    You
                  </span>
                  <span className="inline-flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "hsl(220 12% 55%)" }} />
                    Global avg
                  </span>
                </div>
              </div>
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
              <AllStatsTable
                rows={allStatsRows}
                sort={statSort}
                onSortChange={setStatSort}
                search={statSearch}
                onSearchChange={setStatSearch}
              />
            )}
          </CardSurface>

          {/* Maps the selected hero was played on */}
          <CardSurface flush title={`Maps for ${selected.hero.hero.name}`} icon={<MapIcon size={15} />}>
            {heroMaps.length > 0 ? (
              heroMaps.map((m, i) => {
                const wr = m.winRate * 100;
                return (
                  <div
                    key={m.id}
                    className="grid grid-cols-[26px_1fr_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-2.5 last:border-b-0"
                  >
                    <span className="aqt-mono text-[11px] text-[color:var(--aqt-fg-faint)]">
                      {String(i + 1).padStart(2, "0")}
                    </span>
                    <div className="flex min-w-0 flex-col">
                      <span className="truncate text-[13px] font-medium text-[color:var(--aqt-fg)]">{m.name}</span>
                      <span className="aqt-mono text-[10px] uppercase tracking-[0.06em] text-[color:var(--aqt-fg-dim)]">
                        {m.mode}
                      </span>
                    </div>
                    <span
                      className="aqt-mono text-right text-[12.5px] font-bold"
                      style={{ color: wr >= 55 ? "var(--aqt-emerald)" : wr < 45 ? "var(--aqt-rose)" : "var(--aqt-amber)" }}
                    >
                      {wr.toFixed(0)}%
                    </span>
                    <span className="aqt-mono text-right text-[11.5px] text-[color:var(--aqt-fg-muted)]">
                      {m.win}-{m.loss}
                    </span>
                  </div>
                );
              })
            ) : (
              <div className="py-6 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">
                No map data for this hero yet.
              </div>
            )}
          </CardSurface>
        </div>
      </div>
    </div>
  );
};

const QuickStat = ({ label, value, delta }: { label: string; value: string; delta: number | null }) => (
  <div className="flex flex-col items-end gap-0.5">
    <span className="text-[9.5px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{label}</span>
    <span className="aqt-display text-[28px] font-bold leading-none">{value}</span>
    {delta != null ? (
      <span
        className="aqt-mono text-[10.5px] font-bold"
        style={{ color: delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
      >
        {formatDelta(delta)}
      </span>
    ) : null}
  </div>
);

interface AllStatsRow {
  name: LogStatsName;
  label: string;
  overall: number;
  bestYou: number | undefined;
  avg10: number;
  delta: number | null;
  bestAll: number | null;
  global10: number;
  isRecord: boolean;
}

const AllStatsTable = ({
  rows,
  sort,
  onSortChange,
  search,
  onSearchChange
}: {
  rows: AllStatsRow[];
  sort: StatSortKey;
  onSortChange: (key: StatSortKey) => void;
  search: string;
  onSearchChange: (value: string) => void;
}) => {
  // Plain render helper (not a component) to avoid recreating a component during render.
  const sortTh = (label: string, k: StatSortKey, align: "left" | "right" = "right") => (
    <th
      onClick={() => onSortChange(k)}
      className={cn(
        "aqt-mono cursor-pointer select-none border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-[10px] font-bold uppercase tracking-[0.1em]",
        align === "right" ? "text-right" : "text-left",
        sort === k ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-faint)] hover:text-[color:var(--aqt-fg-muted)]"
      )}
    >
      {label}
      {sort === k ? " ↓" : ""}
    </th>
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="relative min-w-[180px] max-w-[280px] flex-1">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[color:var(--aqt-fg-faint)]">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            placeholder="Search stats…"
            value={search}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.025)] px-3 py-1.5 pl-8 text-[12.5px] text-[color:var(--aqt-fg)] outline-none"
          />
        </div>
        <span className="aqt-mono text-[10.5px] text-[color:var(--aqt-fg-faint)]">♔ = holds the all-players record</span>
      </div>
      <div className="overflow-x-auto">
        <table className="aqt-tnum w-full border-collapse text-[12.5px]">
          <thead>
            <tr>
              {sortTh("Stat", "name", "left")}
              {sortTh("Overall", "overall")}
              <th className="aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">Best (you)</th>
              {sortTh("Avg /10", "avg10")}
              {sortTh("Δ", "delta")}
              <th className="aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">Best (all)</th>
              <th className="aqt-mono border-b border-[color:var(--aqt-border)] px-3 py-2.5 text-right text-[10px] font-bold uppercase tracking-[0.1em] text-[color:var(--aqt-fg-faint)]">Global /10</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.name} className="border-b border-[color:var(--aqt-border)] last:border-b-0 hover:bg-[hsl(0_0%_100%/0.02)]">
                <td className="px-3 py-2 text-left font-medium text-[color:var(--aqt-fg)]">
                  {r.label}
                  {r.isRecord ? <span className="ml-1.5 text-[color:var(--aqt-amber)]" title="Holds the all-players record">♔</span> : null}
                </td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">{formatStatValue(r.name, r.overall)}</td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-muted)]">
                  {r.bestYou != null ? formatStatValue(r.name, r.bestYou) : "—"}
                </td>
                <td className="aqt-mono px-3 py-2 text-right font-semibold text-[color:var(--aqt-fg)]">{formatStatValue(r.name, r.avg10)}</td>
                <td
                  className="aqt-mono px-3 py-2 text-right font-bold"
                  style={{ color: r.delta == null ? "var(--aqt-fg-faint)" : r.delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                >
                  {r.delta != null ? formatDelta(r.delta) : "—"}
                </td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">
                  {r.bestAll != null ? formatStatValue(r.name, r.bestAll) : "—"}
                </td>
                <td className="aqt-mono px-3 py-2 text-right text-[color:var(--aqt-fg-dim)]">{formatStatValue(r.name, r.global10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {rows.length === 0 ? (
          <div className="py-8 text-center text-[12px] text-[color:var(--aqt-fg-dim)]">No stats match search</div>
        ) : null}
      </div>
    </div>
  );
};

export default HeroesView;
