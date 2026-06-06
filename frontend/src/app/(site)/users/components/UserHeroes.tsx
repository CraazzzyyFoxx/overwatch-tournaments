"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import { BarChart3, Search, TrendingDown, TrendingUp } from "lucide-react";

import { cn } from "@/lib/utils";
import { HeroPlaytime, HeroWithUserStats } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";
import { getHumanizedStats } from "@/utils/stats";

import CustomSelect from "@/components/CustomSelect";
import HeroPlaytimeChart from "@/components/HeroPlaytimeChart";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { ScrollArea, ScrollBar } from "@/components/ui/scroll-area";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { TooltipProvider } from "@/components/ui/tooltip";
import { useLiquidGlass } from "@/app/(site)/users/components/UserLiquidGlassProvider";
import { BestResult, HeroListItem, KpiCard } from "@/app/(site)/users/components/user-heroes/presentation";
import {
  RGB,
  computeDelta,
  formatDelta,
  formatPercent,
  formatSeconds,
  formatStatValue,
  getOverall,
  isRevertedStat,
  mix,
  parseHexColor,
  toCssVarRgb
} from "@/app/(site)/users/components/user-heroes/utils";

const UserHeroes = ({ heroes, filterSlot }: { heroes: HeroWithUserStats[]; filterSlot?: React.ReactNode }) => {
  const safeHeroes = Array.isArray(heroes) ? heroes : [];

  const HERO_POOL_LIMIT = 10;
  const EFFECTIVENESS_MIN_PLAYTIME_SECONDS = 30 * 60;

  const heroesWithPlaytime = useMemo(() => {
    const items = safeHeroes
      .map((h) => {
        const playtimeSeconds = getOverall(h, LogStatsName.HeroTimePlayed);
        return { hero: h, playtimeSeconds };
      })
      .sort((a, b) => b.playtimeSeconds - a.playtimeSeconds);

    const totalSeconds = items.reduce((sum, item) => sum + item.playtimeSeconds, 0);

    return {
      totalSeconds,
      items: items.map((item) => ({
        ...item,
        share: totalSeconds > 0 ? item.playtimeSeconds / totalSeconds : 0
      }))
    };
  }, [safeHeroes]);

  const defaultHeroId = heroesWithPlaytime.items[0]?.hero.hero.id ?? 0;
  const [selectedHeroId, setSelectedHeroId] = useState<number>(() => defaultHeroId);

  const exists = heroesWithPlaytime.items.some((item) => item.hero.hero.id === selectedHeroId);
  const targetHeroId = exists ? selectedHeroId : defaultHeroId;

  if (targetHeroId !== selectedHeroId) {
    setSelectedHeroId(targetHeroId);
  }

  const selected = useMemo(() => {
    return (
      heroesWithPlaytime.items.find((item) => item.hero.hero.id === selectedHeroId) ??
      heroesWithPlaytime.items[0] ??
      null
    );
  }, [heroesWithPlaytime.items, selectedHeroId]);

  const selectedHero = selected?.hero ?? null;
  const selectedPlaytimeSeconds = selected?.playtimeSeconds ?? 0;
  const selectedShare = selected?.share ?? 0;

  const { setAura } = useLiquidGlass();

  useEffect(() => {
    if (!selectedHero) {
      return;
    }
    const heroRgb = parseHexColor(selectedHero.hero.color);
    if (!heroRgb) {
      return;
    }

    const sky: RGB = { r: 56, g: 189, b: 248 };
    const amber: RGB = { r: 245, g: 158, b: 11 };
    const b = mix(heroRgb, sky, 0.55);
    const c = mix(heroRgb, amber, 0.55);
    setAura({ a: toCssVarRgb(heroRgb), b: toCssVarRgb(b), c: toCssVarRgb(c) });
  }, [selectedHero, setAura]);

  const heroPlaytimeData = useMemo<HeroPlaytime[]>(() => {
    return heroesWithPlaytime.items.map((item) => ({
      hero: item.hero.hero,
      playtime: item.share
    }));
  }, [heroesWithPlaytime.items]);

  const [showAllChart, setShowAllChart] = useState(false);
  const displayChartData = useMemo(() => {
    if (showAllChart) {
      return heroPlaytimeData;
    }
    return heroPlaytimeData.slice(0, HERO_POOL_LIMIT);
  }, [heroPlaytimeData, showAllChart]);

  const mainHero = heroesWithPlaytime.items[0]?.hero ?? null;
  const mainHeroShare = heroesWithPlaytime.items[0]?.share ?? 0;

  type HeroEffectivenessSummary = {
    hero: HeroWithUserStats;
    playtimeSeconds: number;
    share: number;
    betterCount: number;
    worseCount: number;
    totalCompared: number;
    score: number;
  };

  const heroEffectiveness = useMemo<HeroEffectivenessSummary[]>(() => {
    return heroesWithPlaytime.items
      .map((item) => {
        let betterCount = 0;
        let worseCount = 0;
        let totalCompared = 0;

        for (const stat of item.hero.stats) {
          if (stat.name === LogStatsName.HeroTimePlayed) {
            continue;
          }
          if (!Number.isFinite(stat.avg_10) || !Number.isFinite(stat.avg_10_all) || stat.avg_10_all <= 0) {
            continue;
          }

          totalCompared += 1;

          if (stat.avg_10 === stat.avg_10_all) {
            continue;
          }

          const reversed = isRevertedStat(stat.name);
          const isBetter = reversed ? stat.avg_10 < stat.avg_10_all : stat.avg_10 > stat.avg_10_all;
          if (isBetter) {
            betterCount += 1;
          } else {
            worseCount += 1;
          }
        }

        return {
          hero: item.hero,
          playtimeSeconds: item.playtimeSeconds,
          share: item.share,
          betterCount,
          worseCount,
          totalCompared,
          score: betterCount - worseCount
        };
      })
      .filter((row) => row.totalCompared > 0);
  }, [heroesWithPlaytime.items]);

  const effectivenessCandidates = useMemo(() => {
    const filtered = heroEffectiveness.filter(
      (row) => row.playtimeSeconds >= EFFECTIVENESS_MIN_PLAYTIME_SECONDS
    );
    return filtered.length ? filtered : heroEffectiveness;
  }, [EFFECTIVENESS_MIN_PLAYTIME_SECONDS, heroEffectiveness]);

  const mostEffectiveHero = useMemo(() => {
    let best: HeroEffectivenessSummary | null = null;
    for (const row of effectivenessCandidates) {
      if (!best) {
        best = row;
        continue;
      }
      if (row.betterCount > best.betterCount) {
        best = row;
        continue;
      }
      if (row.betterCount === best.betterCount && row.score > best.score) {
        best = row;
        continue;
      }
      if (
        row.betterCount === best.betterCount &&
        row.score === best.score &&
        row.playtimeSeconds > best.playtimeSeconds
      ) {
        best = row;
      }
    }
    return best;
  }, [effectivenessCandidates]);

  const weakestHero = useMemo(() => {
    let worst: HeroEffectivenessSummary | null = null;
    for (const row of effectivenessCandidates) {
      if (!worst) {
        worst = row;
        continue;
      }
      if (row.worseCount > worst.worseCount) {
        worst = row;
        continue;
      }
      if (row.worseCount === worst.worseCount && row.score < worst.score) {
        worst = row;
        continue;
      }
      if (
        row.worseCount === worst.worseCount &&
        row.score === worst.score &&
        row.playtimeSeconds > worst.playtimeSeconds
      ) {
        worst = row;
      }
    }
    return worst;
  }, [effectivenessCandidates]);

  const heroesSelectItems = useMemo(() => {
    return heroesWithPlaytime.items.map((item) => ({
      value: item.hero.hero.id,
      label: item.hero.hero.name,
      item: (
        <div className="flex items-center gap-2">
          <Image
            src={item.hero.hero.image_path}
            alt={item.hero.hero.name}
            height={24}
            width={24}
            className="object-contain select-none"
          />
          <span className="ml-1">{item.hero.hero.name}</span>
        </div>
      )
    }));
  }, [heroesWithPlaytime.items]);

  const [heroQuery, setHeroQuery] = useState("");
  const filteredHeroItems = useMemo(() => {
    const q = heroQuery.trim().toLowerCase();
    if (!q) {
      return heroesWithPlaytime.items;
    }
    return heroesWithPlaytime.items.filter((item) => item.hero.hero.name.toLowerCase().includes(q));
  }, [heroQuery, heroesWithPlaytime.items]);

  const detailsRef = useRef<HTMLDivElement | null>(null);
  const [detailsHeight, setDetailsHeight] = useState<number | null>(null);
  const [isLg, setIsLg] = useState(false);

  if (!isLg && detailsHeight !== null) {
    setDetailsHeight(null);
  }

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 1024px)");
    const onChange = () => setIsLg(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  useEffect(() => {
    if (!isLg) return;

    const el = detailsRef.current;
    if (!el) {
      return;
    }

    const update = () => {
      setDetailsHeight(el.getBoundingClientRect().height);
    };

    update();

    if (typeof ResizeObserver === "undefined") {
      const onResize = () => update();
      window.addEventListener("resize", onResize);
      return () => window.removeEventListener("resize", onResize);
    }

    const ro = new ResizeObserver(() => update());
    ro.observe(el);
    return () => ro.disconnect();
  }, [isLg]);

  const roleHint = selectedHero
    ? ((selectedHero.hero as unknown as { type?: string; role?: string }).type ??
        (selectedHero.hero as unknown as { type?: string; role?: string }).role)
    : null;

  const keyStatNames: LogStatsName[] = useMemo(
    () => [
      LogStatsName.Eliminations,
      LogStatsName.HeroDamageDealt,
      LogStatsName.HealingDealt,
      LogStatsName.Deaths
    ],
    []
  );

  const keyStats = useMemo(() => {
    if (!selectedHero) {
      return [] as Array<{
        name: LogStatsName;
        label: string;
        value: string;
        global: string;
        delta: number | null;
      }>;
    }

    const out = [] as Array<{
      name: LogStatsName;
      label: string;
      value: string;
      global: string;
      delta: number | null;
    }>;

    for (const name of keyStatNames) {
      const stat = selectedHero.stats.find((s) => s.name === name);
      if (!stat || !Number.isFinite(stat.avg_10) || !Number.isFinite(stat.avg_10_all)) {
        continue;
      }
      if (stat.avg_10_all <= 0) {
        continue;
      }
      const reversed = isRevertedStat(name);
      out.push({
        name,
        label: getHumanizedStats(name),
        value: formatStatValue(name, stat.avg_10),
        global: formatStatValue(name, stat.avg_10_all),
        delta: computeDelta(stat.avg_10, stat.avg_10_all, reversed)
      });
    }

    return out;
  }, [keyStatNames, selectedHero]);

  const comparableStats = useMemo(() => {
    if (!selectedHero) {
      return [] as Array<{
        name: LogStatsName;
        label: string;
        userAvg: number;
        globalAvg: number;
        delta: number;
        reversed: boolean;
        stat: HeroWithUserStats["stats"][number];
      }>;
    }

    const rows = selectedHero.stats
      .filter((s) => s.name !== LogStatsName.HeroTimePlayed)
      .filter((s) => Number.isFinite(s.avg_10) && Number.isFinite(s.avg_10_all) && s.avg_10_all > 0)
      .map((s) => {
        const reversed = isRevertedStat(s.name);
        const delta = computeDelta(s.avg_10, s.avg_10_all, reversed) ?? 0;
        return {
          name: s.name,
          label: getHumanizedStats(s.name),
          userAvg: s.avg_10,
          globalAvg: s.avg_10_all,
          delta,
          reversed,
          stat: s
        };
      });

    return rows;
  }, [selectedHero]);

  const strengths = useMemo(() => {
    return [...comparableStats]
      .filter((r) => r.delta > 0)
      .sort((a, b) => b.delta - a.delta)
      .slice(0, 3);
  }, [comparableStats]);

  const weakSpots = useMemo(() => {
    return [...comparableStats]
      .filter((r) => r.delta < 0)
      .sort((a, b) => a.delta - b.delta)
      .slice(0, 3);
  }, [comparableStats]);

  type StatSortKey = "delta" | "overall" | "name";
  const [statSort, setStatSort] = useState<StatSortKey>("delta");
  const [statQuery, setStatQuery] = useState("");

  const tableRows = useMemo(() => {
    const q = statQuery.trim().toLowerCase();
    const rows = comparableStats.filter((r) => (q ? r.label.toLowerCase().includes(q) : true));

    if (statSort === "name") {
      rows.sort((a, b) => a.label.localeCompare(b.label));
    } else if (statSort === "overall") {
      rows.sort((a, b) => (b.stat.overall ?? 0) - (a.stat.overall ?? 0));
    } else {
      rows.sort((a, b) => b.delta - a.delta);
    }

    return rows;
  }, [comparableStats, statQuery, statSort]);

  if (!selectedHero) {
    return (
      <Card>
        <CardContent className="py-10 text-sm text-muted-foreground">
          No hero stats available yet.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div className="grid gap-4 lg:grid-cols-3 lg:items-stretch">
        <Card className="relative h-full overflow-hidden lg:col-span-2">
          <div className="pointer-events-none absolute inset-0">
            <div
              className="absolute -top-24 -left-24 h-72 w-72 rounded-full blur-3xl"
              style={{ backgroundColor: "rgb(var(--lg-a) / 0.12)" }}
            />
            <div
              className="absolute -top-28 right-0 h-80 w-80 rounded-full blur-3xl"
              style={{ backgroundColor: "rgb(var(--lg-b) / 0.10)" }}
            />
            <div
              className="absolute -bottom-24 left-1/3 h-80 w-80 rounded-full blur-3xl"
              style={{ backgroundColor: "rgb(var(--lg-c) / 0.08)" }}
            />
          </div>
          <CardHeader className="relative p-4 pb-2">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <BarChart3 className="h-5 w-5 text-muted-foreground" aria-hidden />
                  <CardTitle className="text-base">Hero pool</CardTitle>
                </div>
                <CardDescription>
                  Playtime share across heroes (based on tracked time &gt; 60s).
                </CardDescription>
              </div>
              <div className="flex shrink-0 items-center gap-2">
                {filterSlot}
                {heroPlaytimeData.length > HERO_POOL_LIMIT ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setShowAllChart((v) => !v)}
                  >
                    {showAllChart ? "Show top" : "Show all"}
                  </Button>
                ) : null}
              </div>
            </div>
          </CardHeader>
          <div className="relative px-3 pb-4">
            {showAllChart ? (
              <ScrollArea className="h-[340px] pr-2">
                <HeroPlaytimeChart
                  heroes={displayChartData}
                  rowHeight={32}
                  barSize={24}
                  iconSize={24}
                  minHeight={220}
                />
              </ScrollArea>
            ) : (
              <HeroPlaytimeChart
                heroes={displayChartData}
                rowHeight={32}
                barSize={24}
                iconSize={24}
                minHeight={220}
              />
            )}
          </div>
        </Card>

        <div className="grid content-start gap-3 sm:grid-cols-2 lg:grid-cols-1">
          <KpiCard
            label="Total playtime"
            value={formatSeconds(heroesWithPlaytime.totalSeconds)}
            subtitle={`${heroesWithPlaytime.items.length} heroes`}
          />
          <KpiCard
            label="Main hero"
            value={mainHero ? mainHero.hero.name : "-"}
            subtitle={mainHero ? `Share: ${formatPercent(mainHeroShare, 0)}` : "-"}
          />
          <KpiCard
            label="Most effective"
            value={mostEffectiveHero ? mostEffectiveHero.hero.hero.name : "-"}
            subtitle={
              mostEffectiveHero
                ? `Better vs avg: ${mostEffectiveHero.betterCount}/${mostEffectiveHero.totalCompared}  •  ${formatSeconds(mostEffectiveHero.playtimeSeconds)}`
                : "-"
            }
          />
          <KpiCard
            label="Weakest"
            value={weakestHero ? weakestHero.hero.hero.name : "-"}
            subtitle={
              weakestHero
                ? `Worse vs avg: ${weakestHero.worseCount}/${weakestHero.totalCompared}  •  ${formatSeconds(weakestHero.playtimeSeconds)}`
                : "-"
            }
          />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-12 lg:items-start">
        <Card
          className="hidden md:flex lg:col-span-4 flex-col overflow-hidden"
          style={isLg && detailsHeight ? { height: detailsHeight } : undefined}
        >
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Heroes</CardTitle>
            <CardDescription>
              Search and pick a hero to inspect personal stats and global bests.
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0 flex flex-col flex-1 min-h-0">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" aria-hidden />
              <Input
                value={heroQuery}
                onChange={(e) => setHeroQuery(e.target.value)}
                type="search"
                placeholder="Search heroes..."
                className="pl-8"
              />
            </div>
            <div className="mt-4 flex-1 min-h-0">
              <ScrollArea className="h-full pr-3">
                <div className="space-y-2">
                  {filteredHeroItems.map((item) => (
                    <HeroListItem
                      key={item.hero.hero.id}
                      hero={item.hero}
                      selected={item.hero.hero.id === selectedHeroId}
                      onSelect={() => setSelectedHeroId(item.hero.hero.id)}
                      playtimeSeconds={item.playtimeSeconds}
                      share={item.share}
                    />
                  ))}
                </div>
              </ScrollArea>
            </div>
          </CardContent>
        </Card>

        <div ref={detailsRef} className="lg:col-span-8 min-w-0 space-y-6">
          {/* Mobile quick selector */}
          <Card className="md:hidden">
            <CardContent className="pt-6">
              <CustomSelect
                className="w-full"
                items={heroesSelectItems}
                value={selectedHeroId}
                onSelect={(value) => setSelectedHeroId(value)}
              />
            </CardContent>
          </Card>

          <Card className="relative overflow-hidden">
            <div className="pointer-events-none absolute inset-0">
              <div
                className="absolute -top-20 -left-20 h-64 w-64 rounded-full blur-3xl"
                style={{ backgroundColor: "rgb(var(--lg-a) / 0.10)" }}
              />
              <div
                className="absolute -bottom-24 right-0 h-72 w-72 rounded-full blur-3xl"
                style={{ backgroundColor: "rgb(var(--lg-b) / 0.08)" }}
              />
              <div className="absolute inset-0 bg-gradient-to-b from-transparent via-transparent to-background/35" />
            </div>
            <CardHeader className="relative pb-3">
              <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <CardTitle className="text-xl">{selectedHero.hero.name}</CardTitle>
                    {roleHint ? <Badge variant="secondary">{roleHint}</Badge> : null}
                    <Badge variant="outline">Share {formatPercent(selectedShare, 0)}</Badge>
                  </div>
                  <div className="mt-1 text-sm text-muted-foreground">
                    Playtime {formatSeconds(selectedPlaytimeSeconds, { withSeconds: true })}
                  </div>
                </div>
                <div className="text-sm text-muted-foreground">
                  <span className="font-medium text-foreground tabular-nums">
                    {heroesWithPlaytime.items.length}
                  </span>{" "}
                  heroes tracked
                </div>
              </div>
            </CardHeader>
            <CardContent className="relative">
              <div className="grid gap-4 md:grid-cols-12">
                <div className="md:col-span-4">
                  <div
                    className="relative aspect-square w-full overflow-hidden rounded-2xl border-4 shadow-sm"
                    style={{ borderColor: selectedHero.hero.color }}
                  >
                    <Image
                      className="object-contain select-none"
                      src={selectedHero.hero.image_path}
                      alt={selectedHero.hero.name}
                      fill
                    />
                  </div>
                  <div className="mt-4">
                    <div className="flex items-center justify-between text-xs text-muted-foreground">
                      <span>Share of playtime</span>
                      <span className="tabular-nums">{formatPercent(selectedShare, 0)}</span>
                    </div>
                    <div className="mt-2">
                      <Progress
                        value={Math.max(0, Math.min(100, selectedShare * 100))}
                        className="bg-muted/40 [&>div]:bg-foreground/80"
                        aria-label="Selected hero playtime share"
                      />
                    </div>
                  </div>
                </div>

                <div className="md:col-span-8">
                  <div className="grid gap-3 sm:grid-cols-2">
                    {keyStats.length > 0 ? (
                      keyStats.map((kpi) => {
                        const delta = kpi.delta;
                        const deltaClass =
                          delta === null
                            ? "text-muted-foreground"
                            : delta >= 0
                              ? "text-emerald-400"
                              : "text-rose-400";
                        const Icon =
                          delta === null ? null : delta >= 0 ? TrendingUp : TrendingDown;

                        return (
                          <div
                            key={kpi.name}
                            className="rounded-xl border bg-background/15 p-3"
                          >
                            <div className="flex items-start justify-between gap-3">
                              <div className="text-xs font-semibold text-muted-foreground">
                                {kpi.label}
                              </div>
                              <div className={cn("flex items-center gap-1 text-xs font-semibold tabular-nums", deltaClass)}>
                                {Icon ? <Icon className="h-4 w-4" aria-hidden /> : null}
                                {delta === null ? "-" : formatDelta(delta)}
                              </div>
                            </div>
                            <div className="mt-1 text-2xl font-bold tabular-nums">{kpi.value}</div>
                            <div className="mt-1 text-[11px] text-muted-foreground">
                              Global avg/10: <span className="tabular-nums">{kpi.global}</span>
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <div className="rounded-xl border bg-background/15 p-4 text-sm text-muted-foreground">
                        Not enough data to compute key comparisons for this hero.
                      </div>
                    )}
                  </div>
                  <div className="mt-4 text-[11px] text-muted-foreground">
                    Deltas are computed vs global averages. For some stats (Deaths, Damage taken), lower is better.
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="overflow-hidden">
            <Tabs defaultValue="highlights" className="w-full">
              <CardHeader className="pb-2">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <CardTitle className="text-base">Insights</CardTitle>
                    <CardDescription>
                      Highlights and full stat breakdown for {selectedHero.hero.name}.
                    </CardDescription>
                  </div>
                  <TabsList>
                    <TabsTrigger value="highlights">Highlights</TabsTrigger>
                    <TabsTrigger value="all">All stats</TabsTrigger>
                  </TabsList>
                </div>
              </CardHeader>
              <CardContent className="pt-0">
                <TabsContent value="highlights" className="mt-0">
                  <div className="grid gap-4 md:grid-cols-2">
                    <div className="rounded-xl border bg-background/15 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold">Strengths</div>
                        <Badge variant="outline">vs global</Badge>
                      </div>
                      <div className="mt-3 space-y-2">
                        {strengths.length > 0 ? (
                          strengths.map((row) => (
                            <div
                              key={row.name}
                              className="flex items-start justify-between gap-3 rounded-lg border border-border/50 bg-muted/10 px-3 py-2"
                            >
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{row.label}</div>
                                <div className="mt-0.5 text-[11px] text-muted-foreground tabular-nums">
                                  You {formatStatValue(row.name, row.userAvg)} • Global {formatStatValue(row.name, row.globalAvg)}
                                </div>
                              </div>
                              <div className="flex items-center gap-1 text-sm font-semibold tabular-nums text-emerald-400">
                                <TrendingUp className="h-4 w-4" aria-hidden />
                                {formatDelta(row.delta)}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="text-sm text-muted-foreground">
                            No strong outliers yet.
                          </div>
                        )}
                      </div>
                    </div>

                    <div className="rounded-xl border bg-background/15 p-4">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-sm font-semibold">Weak spots</div>
                        <Badge variant="outline">vs global</Badge>
                      </div>
                      <div className="mt-3 space-y-2">
                        {weakSpots.length > 0 ? (
                          weakSpots.map((row) => (
                            <div
                              key={row.name}
                              className="flex items-start justify-between gap-3 rounded-lg border border-border/50 bg-muted/10 px-3 py-2"
                            >
                              <div className="min-w-0">
                                <div className="text-sm font-medium truncate">{row.label}</div>
                                <div className="mt-0.5 text-[11px] text-muted-foreground tabular-nums">
                                  You {formatStatValue(row.name, row.userAvg)} • Global {formatStatValue(row.name, row.globalAvg)}
                                </div>
                              </div>
                              <div className="flex items-center gap-1 text-sm font-semibold tabular-nums text-rose-400">
                                <TrendingDown className="h-4 w-4" aria-hidden />
                                {formatDelta(row.delta)}
                              </div>
                            </div>
                          ))
                        ) : (
                          <div className="text-sm text-muted-foreground">
                            No weak spots detected.
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </TabsContent>

                <TabsContent value="all" className="mt-0">
                  <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
                    <div className="relative md:w-[320px]">
                      <Search
                        className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground"
                        aria-hidden
                      />
                      <Input
                        value={statQuery}
                        onChange={(e) => setStatQuery(e.target.value)}
                        type="search"
                        placeholder="Filter stats..."
                        className="pl-8"
                      />
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        type="button"
                        variant={statSort === "delta" ? "default" : "outline"}
                        onClick={() => setStatSort("delta")}
                      >
                        Sort: Delta
                      </Button>
                      <Button
                        type="button"
                        variant={statSort === "overall" ? "default" : "outline"}
                        onClick={() => setStatSort("overall")}
                      >
                        Sort: Overall
                      </Button>
                      <Button
                        type="button"
                        variant={statSort === "name" ? "default" : "outline"}
                        onClick={() => setStatSort("name")}
                      >
                        Sort: Name
                      </Button>
                    </div>
                  </div>

                  {/* Mobile cards */}
                  <div className="mt-4 space-y-3 md:hidden">
                    {tableRows.map((row) => {
                      const delta = row.delta;
                      const deltaClass = delta >= 0 ? "text-emerald-400" : "text-rose-400";
                      const Icon = delta >= 0 ? TrendingUp : TrendingDown;
                      return (
                        <Card key={row.name} className="overflow-hidden">
                          <CardContent className="pt-4">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0">
                                <div className="font-semibold truncate">{row.label}</div>
                                <div className="mt-1 text-xs text-muted-foreground tabular-nums">
                                  Overall: {formatStatValue(row.name, row.stat.overall)}
                                </div>
                              </div>
                              <div className={cn("flex items-center gap-1 text-sm font-semibold tabular-nums", deltaClass)}>
                                <Icon className="h-4 w-4" aria-hidden />
                                {formatDelta(delta)}
                              </div>
                            </div>

                            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                              <div className="rounded-lg border border-border/50 bg-muted/10 px-3 py-2">
                                <div className="text-muted-foreground">Your avg/10</div>
                                <div className="mt-0.5 text-base font-bold tabular-nums">
                                  {formatStatValue(row.name, row.userAvg)}
                                </div>
                              </div>
                              <div className="rounded-lg border border-border/50 bg-muted/10 px-3 py-2">
                                <div className="text-muted-foreground">Global avg/10</div>
                                <div className="mt-0.5 text-base font-bold tabular-nums">
                                  {formatStatValue(row.name, row.globalAvg)}
                                </div>
                              </div>
                            </div>

                            <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
                              <div className="rounded-lg border border-border/50 bg-muted/10 px-3 py-2">
                                <div className="text-muted-foreground">Best (you)</div>
                                <div className="mt-1">
                                  <TooltipProvider>
                                    <BestResult
                                      name={row.name}
                                      stat={row.stat.best}
                                      best={row.stat.best_all}
                                      all={false}
                                    />
                                  </TooltipProvider>
                                </div>
                              </div>
                              <div className="rounded-lg border border-border/50 bg-muted/10 px-3 py-2">
                                <div className="text-muted-foreground">Best (all)</div>
                                <div className="mt-1">
                                  <TooltipProvider>
                                    <BestResult
                                      name={row.name}
                                      stat={row.stat.best_all}
                                      best={row.stat.best_all}
                                      all={true}
                                    />
                                  </TooltipProvider>
                                </div>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>

                  {/* Desktop table */}
                  <div className="mt-4 hidden md:block">
                    <ScrollArea>
                      <CardContent className="p-0">
                        <TooltipProvider>
                          <Table>
                            <TableHeader>
                              <TableRow>
                                <TableHead className="text-left">Name</TableHead>
                                <TableHead className="text-right">Overall</TableHead>
                                <TableHead className="text-left">Best (you)</TableHead>
                                <TableHead className="text-right">Avg/10</TableHead>
                                <TableHead className="text-right">Delta</TableHead>
                                <TableHead className="text-left">Best (all)</TableHead>
                                <TableHead className="text-right">Global avg/10</TableHead>
                              </TableRow>
                            </TableHeader>
                            <TableBody>
                              {tableRows.map((row) => {
                                const stat = row.stat;
                                const delta = row.delta;
                                const deltaClass = delta >= 0 ? "text-emerald-400" : "text-rose-400";
                                const Icon = delta >= 0 ? TrendingUp : TrendingDown;

                                return (
                                  <TableRow key={row.name}>
                                    <TableCell className="font-medium">{row.label}</TableCell>
                                    <TableCell className="text-right tabular-nums">
                                      {formatStatValue(row.name, stat.overall)}
                                    </TableCell>
                                    <TableCell>
                                      <BestResult
                                        name={row.name}
                                        stat={stat.best}
                                        best={stat.best_all}
                                        all={false}
                                      />
                                    </TableCell>
                                    <TableCell className="text-right tabular-nums">
                                      {formatStatValue(row.name, stat.avg_10)}
                                    </TableCell>
                                    <TableCell className={cn("text-right tabular-nums font-semibold", deltaClass)}>
                                      <span className="inline-flex items-center gap-1">
                                        <Icon className="h-4 w-4" aria-hidden />
                                        {formatDelta(delta)}
                                      </span>
                                    </TableCell>
                                    <TableCell>
                                      <BestResult
                                        name={row.name}
                                        stat={stat.best_all}
                                        best={stat.best_all}
                                        all={true}
                                      />
                                    </TableCell>
                                    <TableCell className="text-right tabular-nums">
                                      {formatStatValue(row.name, stat.avg_10_all)}
                                    </TableCell>
                                  </TableRow>
                                );
                              })}
                            </TableBody>
                          </Table>
                        </TooltipProvider>
                      </CardContent>
                      <ScrollBar orientation="horizontal" />
                    </ScrollArea>
                  </div>
                </TabsContent>
              </CardContent>
            </Tabs>
          </Card>
        </div>
      </div>
    </div>
  );
};

export default UserHeroes;
