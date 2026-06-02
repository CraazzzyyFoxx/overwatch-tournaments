"use client";

import React, { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";
import {
  ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent
} from "@/components/ui/chart";
import { RankSeries } from "@/types/rank.types";
import { getTierForRank, DEFAULT_DIVISION_GRID } from "@/lib/division-grid";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { LineChart as ChartIcon, Compass } from "lucide-react";
import { useTranslation } from "@/i18n/LanguageContext";

type GroupBy = "role" | "battle_tag";

const ROLE_COLORS: Record<string, string> = {
  tank: "#f97316",
  damage: "#ef4444",
  support: "#22c55e"
};

const PALETTE = ["#2563eb", "#a855f7", "#06b6d4", "#f59e0b", "#ec4899", "#14b8a6"];

interface LineDef {
  key: string;
  label: string;
  color: string;
}

interface RankHistoryChartProps {
  series: RankSeries[];
  /** Default grouping mode. */
  defaultGroupBy?: GroupBy;
  className?: string;
}

function uniqueBy<T, K>(items: T[], keyOf: (item: T) => K): T[] {
  const seen = new Set<K>();
  const out: T[] = [];
  for (const item of items) {
    const k = keyOf(item);
    if (!seen.has(k)) {
      seen.add(k);
      out.push(item);
    }
  }
  return out;
}

export default function RankHistoryChart({
  series,
  defaultGroupBy = "role",
  className
}: RankHistoryChartProps) {
  const platforms = useMemo(() => uniqueBy(series.map((s) => s.platform), (p) => p), [series]);
  const [platform, setPlatform] = useState<string>(platforms.includes("pc") ? "pc" : platforms[0] ?? "pc");
  const [groupBy, setGroupBy] = useState<GroupBy>(defaultGroupBy);

  const platformSeries = useMemo(
    () => series.filter((s) => s.platform === platform),
    [series, platform]
  );

  const battleTags = useMemo(
    () => uniqueBy(platformSeries, (s) => s.battle_tag_id).map((s) => ({ id: s.battle_tag_id, label: s.battle_tag })),
    [platformSeries]
  );
  const roles = useMemo(() => uniqueBy(platformSeries.map((s) => s.role), (r) => r), [platformSeries]);

  const [fixedBattleTagId, setFixedBattleTagId] = useState<number | undefined>(battleTags[0]?.id);
  const [fixedRole, setFixedRole] = useState<string | undefined>(roles[0]);

  const effectiveBattleTagId =
    battleTags.find((b) => b.id === fixedBattleTagId)?.id ?? battleTags[0]?.id;
  const effectiveRole = roles.includes(fixedRole ?? "") ? fixedRole : roles[0];

  const { lines, data } = useMemo(() => {
    const activeSeries =
      groupBy === "role"
        ? platformSeries.filter((s) => s.battle_tag_id === effectiveBattleTagId)
        : platformSeries.filter((s) => s.role === effectiveRole);

    const lineDefs: LineDef[] = activeSeries.map((s, i) =>
      groupBy === "role"
        ? { key: s.role, label: s.role, color: ROLE_COLORS[s.role] ?? PALETTE[i % PALETTE.length] }
        : { key: `bt${s.battle_tag_id}`, label: s.battle_tag, color: PALETTE[i % PALETTE.length] }
    );

    const rows = new Map<string, Record<string, number | string>>();
    for (const s of activeSeries) {
      const key = groupBy === "role" ? s.role : `bt${s.battle_tag_id}`;
      for (const p of s.points) {
        if (!p.is_ranked || p.rank_value == null) continue;
        const dateKey = p.captured_at.split("T")[0] || p.captured_at;
        const row = rows.get(dateKey) ?? { ts: dateKey };
        row[key] = p.rank_value;
        rows.set(dateKey, row);
      }
    }
    const sorted = [...rows.values()].sort(
      (a, b) => new Date(a.ts as string).getTime() - new Date(b.ts as string).getTime()
    );
    return { lines: lineDefs, data: sorted };
  }, [groupBy, platformSeries, effectiveBattleTagId, effectiveRole]);

  const chartConfig = useMemo<ChartConfig>(() => {
    const cfg: ChartConfig = {};
    for (const l of lines) {
      cfg[l.key] = { label: l.label, color: l.color };
    }
    return cfg;
  }, [lines]);

  const yDomain = useMemo(() => {
    if (data.length === 0) return [0, 5000];
    let minVal = Infinity;
    let maxVal = -Infinity;

    for (const row of data) {
      for (const key of Object.keys(row)) {
        if (key === "ts") continue;
        const val = row[key];
        if (typeof val === "number") {
          if (val < minVal) minVal = val;
          if (val > maxVal) maxVal = val;
        }
      }
    }

    if (minVal === Infinity || maxVal === -Infinity) {
      return [0, 5000];
    }

    const domainMin = Math.max(0, Math.floor(minVal / 500) * 500 - 500);
    const domainMax = Math.min(6000, Math.ceil(maxVal / 500) * 500 + 500);

    if (domainMax - domainMin < 1000) {
      return [Math.max(0, domainMin - 500), Math.min(6000, domainMax + 500)];
    }

    return [domainMin, domainMax];
  }, [data]);

  const { locale } = useTranslation();
  const isRu = locale.startsWith("ru");

  if (series.length === 0) {
    return (
      <div className={`flex flex-col items-center justify-center text-center p-6 rounded-xl border border-white/[0.06] bg-zinc-950/20 ${className || ""}`}>
        <ChartIcon className="h-5 w-5 text-white/30 mb-2" />
        <h4 className="text-xs font-semibold text-white/70 mb-1">
          {isRu ? "История рангов отсутствует" : "No rank history"}
        </h4>
        <p className="text-[11px] text-white/45 max-w-xs leading-normal">
          {isRu
            ? "Соревновательная статистика для этого игрока еще не была собрана."
            : "No competitive rank history has been collected for this player yet."}
        </p>
      </div>
    );
  }

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <Select value={groupBy} onValueChange={(val) => setGroupBy(val as GroupBy)}>
          <SelectTrigger className="w-[130px] h-8 text-xs bg-background/50 border-white/[0.08]">
            <SelectValue placeholder="Group by..." />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="role" className="text-xs">By role</SelectItem>
            <SelectItem value="battle_tag" className="text-xs">By battle.net</SelectItem>
          </SelectContent>
        </Select>

        {groupBy === "role" ? (
          <Select
            value={effectiveBattleTagId != null ? String(effectiveBattleTagId) : undefined}
            onValueChange={(val) => setFixedBattleTagId(Number(val))}
          >
            <SelectTrigger className="w-[170px] h-8 text-xs bg-background/50 border-white/[0.08]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {battleTags.map((b) => (
                <SelectItem key={b.id} value={String(b.id)} className="text-xs">
                  {b.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : (
          <Select
            value={effectiveRole}
            onValueChange={(val) => setFixedRole(val)}
          >
            <SelectTrigger className="w-[110px] h-8 text-xs bg-background/50 border-white/[0.08] capitalize">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {roles.map((r) => (
                <SelectItem key={r} value={r} className="text-xs capitalize">
                  {r}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        {platforms.length > 1 && (
          <Select
            value={platform}
            onValueChange={(val) => setPlatform(val)}
          >
            <SelectTrigger className="w-[80px] h-8 text-xs bg-background/50 border-white/[0.08] uppercase">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {platforms.map((p) => (
                <SelectItem key={p} value={p} className="text-xs uppercase">
                  {p}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </div>

      {data.length === 0 ? (
        <div className="flex flex-col items-center justify-center text-center p-6 rounded-xl border border-white/[0.06] bg-zinc-950/20">
          <Compass className="h-5 w-5 text-white/30 mb-2" />
          <h4 className="text-xs font-semibold text-white/70 mb-1">
            {isRu ? "Нет данных для выбора" : "No data for selection"}
          </h4>
          <p className="text-[11px] text-white/45 max-w-xs leading-normal">
            {isRu
              ? "Выбранная комбинация учетной записи и роли не содержит соревновательных записей."
              : "The selected account or role combination does not contain competitive records."}
          </p>
        </div>
      ) : (
        <div className="relative overflow-hidden rounded-xl border border-white/[0.06] bg-zinc-950/40 p-4 shadow-inner backdrop-blur-xs">
          {/* Glow effect */}
          <div className="absolute -left-12 -top-12 -z-10 size-24 rounded-full bg-primary/5 blur-2xl pointer-events-none" />
          <div className="absolute -right-12 -bottom-12 -z-10 size-24 rounded-full bg-primary/5 blur-2xl pointer-events-none" />

          <ChartContainer config={chartConfig} className="h-[180px] w-full aspect-auto">
            <LineChart accessibilityLayer data={data} margin={{ left: 2, right: 2, top: 4, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke="rgba(255, 255, 255, 0.05)" strokeDasharray="3 3" />
              <XAxis
                dataKey="ts"
                tickLine={false}
                axisLine={false}
                tickMargin={6}
                minTickGap={24}
                tickFormatter={(value) => new Date(value).toLocaleDateString()}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={84}
                tickCount={5}
                domain={yDomain}
                tickFormatter={(val) => {
                  const tier = getTierForRank(DEFAULT_DIVISION_GRID, val);
                  return tier ? tier.name : val.toString();
                }}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(value) => new Date(value).toLocaleDateString()}
                    formatter={(value, name, item) => {
                      const rank = Number(value);
                      const tier = getTierForRank(DEFAULT_DIVISION_GRID, rank);
                      const label = tier ? `${tier.name} (${rank})` : rank.toString();
                      return (
                        <>
                          <div
                            className="shrink-0 rounded-xs border h-2.5 w-2.5"
                            style={{
                              backgroundColor: item.color,
                              borderColor: item.color,
                            }}
                          />
                          <div className="flex flex-1 justify-between items-center leading-none text-xs gap-4">
                            <span className="text-muted-foreground">{chartConfig[name as string]?.label || name}</span>
                            <span className="font-mono font-medium text-foreground ml-2">{label}</span>
                          </div>
                        </>
                      );
                    }}
                  />
                }
              />
              {lines.map((l) => (
                <Line
                  key={l.key}
                  dataKey={l.key}
                  name={l.label}
                  type="monotone"
                  stroke={`var(--color-${l.key})`}
                  strokeWidth={2.5}
                  dot={{ r: 3, strokeWidth: 1 }}
                  activeDot={{ r: 5, strokeWidth: 0 }}
                  connectNulls
                />
              ))}
              <ChartLegend content={<ChartLegendContent className="pt-2" />} />
            </LineChart>
          </ChartContainer>
        </div>
      )}
    </div>
  );
}

export function RankHistorySkeleton({ className }: { className?: string }) {
  return (
    <div className={`space-y-3 ${className || ""}`}>
      <div className="flex flex-wrap items-center gap-3">
        <Skeleton className="w-[130px] h-8 bg-white/[0.04]" />
        <Skeleton className="w-[170px] h-8 bg-white/[0.04]" />
      </div>
      <div className="relative overflow-hidden rounded-xl border border-white/[0.06] bg-zinc-950/40 p-4 shadow-inner">
        <Skeleton className="h-[180px] w-full bg-white/[0.03]" />
      </div>
    </div>
  );
}
