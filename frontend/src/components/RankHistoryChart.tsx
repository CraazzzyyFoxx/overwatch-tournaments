"use client";

import { useMemo, useState } from "react";
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
import { getTierForRank, OW_REFERENCE_GRID } from "@/lib/divisions/grid";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { LineChart as ChartIcon, Compass, type LucideIcon } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";

import type { Granularity } from "@/hooks/useRankHistory";
import { cn } from "@/lib/utils";

type GroupBy = "role" | "battle_tag";

/** Only `dateTime` is needed here; `useFormatter()` and `await getFormatter()` both satisfy it. */
type DateFormatter = Pick<ReturnType<typeof useFormatter>, "dateTime">;

// Design-book role hues (tank=blue, damage=pink, support=green) so this chart
// matches role colours everywhere else. Tokens, not hex: these values are only
// ever emitted by `ChartStyle` into a `--color-<key>` CSS custom property (see
// ui/chart.tsx), and `<Line stroke>` reads that variable — so nothing here is
// ever parsed by JS and `var()` resolves normally.
const ROLE_COLORS: Record<string, string> = {
  tank: "var(--aqt-tank)",
  damage: "var(--aqt-damage)",
  support: "var(--aqt-support)"
};

// Categorical series palette for battle-tag grouping. The five shadcn chart
// tokens hold bare HSL triplets, so they must be wrapped in `hsl()`; the sixth
// slot borrows an existing accent rather than inventing a `--chart-6`.
const PALETTE = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
  "var(--aqt-blue)"
];

const TRIGGER_CLASS =
  "h-8 border-[color:var(--aqt-border-2)] bg-[color:var(--aqt-overlay-1)] text-xs";

const CARD_CLASS =
  "relative overflow-hidden rounded-xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-4 shadow-inner";

// Shared by the x-axis tick and tooltip label: both need the same
// granularity-aware date formatting, falling back to the raw value when it
// isn't a parseable timestamp.
function formatTimestampTick(
  format: DateFormatter,
  value: string | number,
  granularity: Granularity
): string {
  try {
    const date = new Date(value);
    if (isNaN(date.getTime())) return String(value);
    if (granularity === "date") {
      return format.dateTime(date, { dateStyle: "short" });
    }
    return format.dateTime(date, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  } catch {
    return String(value);
  }
}

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
  granularity: Granularity;
  onGranularityChange: (g: Granularity) => void;
}

/**
 * The "nothing to draw" surface for rank-history cards.
 *
 * Deliberately not `<PageStateCard>`: that is a page-level surface (px-6 py-10,
 * section type scale) whereas these states render *inside* a chart card — a
 * 300px sheet column and a table's expanded row — where it would dwarf the
 * chart it stands in for. It also keeps the per-state iconography that tells
 * "no history at all" apart from "nothing for this filter".
 */
export function ChartEmptyState({
  icon: Icon,
  title,
  body,
  tone = "neutral",
  className
}: Readonly<{
  icon: LucideIcon;
  title: string;
  body: string;
  /** `error` announces assertively and accents the icon. */
  tone?: "neutral" | "error";
  className?: string;
}>) {
  const isError = tone === "error";
  return (
    <div
      role={isError ? "alert" : "status"}
      className={cn(
        "flex flex-col items-center justify-center rounded-xl border p-6 text-center",
        isError
          ? "border-[color:var(--aqt-rose)]/25 bg-[color:var(--aqt-rose)]/5"
          : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-overlay-1)]",
        className
      )}
    >
      <Icon
        aria-hidden
        className={cn(
          "mb-2 h-5 w-5",
          isError ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-fg-faint)]"
        )}
      />
      <h4 className="mb-1 text-xs font-semibold text-[color:var(--aqt-fg)]">{title}</h4>
      <p className="max-w-xs text-label leading-normal text-[color:var(--aqt-fg-muted)]">{body}</p>
    </div>
  );
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
  className,
  granularity,
  onGranularityChange
}: Readonly<RankHistoryChartProps>) {
  const platforms = useMemo(() => uniqueBy(series.map((s) => s.platform), (p) => p), [series]);
  const [platform, setPlatform] = useState<string>(platforms.includes("pc") ? "pc" : platforms[0] ?? "pc");
  const [groupBy, setGroupBy] = useState<GroupBy>(defaultGroupBy);

  const platformSeries = useMemo(
    () => series.filter((s) => s.platform === platform),
    [series, platform]
  );

  const battleTags = useMemo(
    () => uniqueBy(platformSeries, (s) => s.social_account_id).map((s) => ({ id: s.social_account_id, label: s.battle_tag })),
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
        ? platformSeries.filter((s) => s.social_account_id === effectiveBattleTagId)
        : platformSeries.filter((s) => s.role === effectiveRole);

    const lineDefs: LineDef[] = activeSeries.map((s, i) =>
      groupBy === "role"
        ? { key: s.role, label: s.role, color: ROLE_COLORS[s.role] ?? PALETTE[i % PALETTE.length] }
        : { key: `bt${s.social_account_id}`, label: s.battle_tag, color: PALETTE[i % PALETTE.length] }
    );

    const rows = new Map<string, Record<string, number | string>>();
    for (const s of activeSeries) {
      const key = groupBy === "role" ? s.role : `bt${s.social_account_id}`;
      for (const p of s.points) {
        if (!p.is_ranked || p.rank_value == null) continue;

        let dateKey = p.captured_at;
        if (granularity === "date") {
          dateKey = p.captured_at.split("T")[0] || p.captured_at;
        } else if (granularity === "hour") {
          if (p.captured_at.includes("T")) {
            dateKey = p.captured_at.split(":")[0] + ":00";
          } else {
            dateKey = p.captured_at.substring(0, 13) + ":00";
          }
        }

        const row = rows.get(dateKey) ?? { ts: dateKey };
        row[key] = p.rank_value;
        rows.set(dateKey, row);
      }
    }
    const sorted = [...rows.values()].sort(
      (a, b) => new Date(a.ts as string).getTime() - new Date(b.ts as string).getTime()
    );
    return { lines: lineDefs, data: sorted };
  }, [groupBy, platformSeries, effectiveBattleTagId, effectiveRole, granularity]);

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

  const t = useTranslations();
  const format = useFormatter();

  if (series.length === 0) {
    return (
      <ChartEmptyState
        className={className}
        icon={ChartIcon}
        title={t("rankHistory.emptyTitle")}
        body={t("rankHistory.emptyBody")}
      />
    );
  }

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <Select value={groupBy} onValueChange={(val) => setGroupBy(val as GroupBy)}>
          <SelectTrigger aria-label={t("rankHistory.groupByLabel")} className={cn(TRIGGER_CLASS, "w-[130px]")}>
            <SelectValue placeholder={t("rankHistory.groupByPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="role" className="text-xs">{t("rankHistory.byRole")}</SelectItem>
            <SelectItem value="battle_tag" className="text-xs">{t("rankHistory.byBattleNet")}</SelectItem>
          </SelectContent>
        </Select>

        {groupBy === "role" ? (
          <Select
            value={effectiveBattleTagId != null ? String(effectiveBattleTagId) : undefined}
            onValueChange={(val) => setFixedBattleTagId(Number(val))}
          >
            <SelectTrigger aria-label={t("rankHistory.accountLabel")} className={cn(TRIGGER_CLASS, "w-[170px]")}>
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
            <SelectTrigger aria-label={t("rankHistory.roleLabel")} className={cn(TRIGGER_CLASS, "w-[110px] capitalize")}>
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

        <Select value={granularity} onValueChange={(val) => onGranularityChange(val as Granularity)}>
          <SelectTrigger
            aria-label={t("rankHistory.granularityPlaceholder")}
            className={cn(TRIGGER_CLASS, "w-[120px]")}
          >
            <SelectValue placeholder={t("rankHistory.granularityPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="date" className="text-xs">{t("rankHistory.daily")}</SelectItem>
            <SelectItem value="hour" className="text-xs">{t("rankHistory.hourly")}</SelectItem>
            <SelectItem value="raw" className="text-xs">{t("rankHistory.allPoints")}</SelectItem>
          </SelectContent>
        </Select>

        {platforms.length > 1 && (
          <Select
            value={platform}
            onValueChange={(val) => setPlatform(val)}
          >
            <SelectTrigger aria-label={t("rankHistory.platformLabel")} className={cn(TRIGGER_CLASS, "w-[80px] uppercase")}>
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
        <ChartEmptyState
          icon={Compass}
          title={t("rankHistory.noDataTitle")}
          body={t("rankHistory.noDataBody")}
        />
      ) : (
        <div className={cn(CARD_CLASS, "backdrop-blur-xs")}>
          {/* Glow effect */}
          <div className="absolute -left-12 -top-12 -z-10 size-24 rounded-full bg-primary/5 blur-2xl pointer-events-none" />
          <div className="absolute -right-12 -bottom-12 -z-10 size-24 rounded-full bg-primary/5 blur-2xl pointer-events-none" />

          <ChartContainer config={chartConfig} className="h-[180px] w-full aspect-auto">
            <LineChart accessibilityLayer data={data} margin={{ left: 2, right: 2, top: 4, bottom: 0 }}>
              {/* No `stroke`: recharts' `#ccc` default is what ChartContainer
                  restyles to the themed `stroke-border/50`. */}
              <CartesianGrid vertical={false} strokeDasharray="3 3" />
              <XAxis
                dataKey="ts"
                tickLine={false}
                axisLine={false}
                tickMargin={6}
                minTickGap={24}
                tickFormatter={(value) => formatTimestampTick(format, value, granularity)}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                width={84}
                tickCount={5}
                domain={yDomain}
                tickFormatter={(val) => {
                  const tier = getTierForRank(OW_REFERENCE_GRID, val);
                  return tier ? tier.name : val.toString();
                }}
              />
              <ChartTooltip
                content={
                  <ChartTooltipContent
                    labelFormatter={(value) => formatTimestampTick(format, value, granularity)}
                    formatter={(value, name, item) => {
                      const rank = Number(value);
                      const tier = getTierForRank(OW_REFERENCE_GRID, rank);
                      const label = tier ? `${tier.name} (${rank})` : rank.toString();
                      return (
                        <>
                          <div
                            aria-hidden
                            className="shrink-0 rounded-xs border h-2.5 w-2.5"
                            style={{
                              backgroundColor: item.color,
                              borderColor: item.color,
                            }}
                          />
                          <div className="flex flex-1 justify-between items-center leading-none text-xs gap-4">
                            <span className="text-[color:var(--aqt-fg-muted)]">{chartConfig[name as string]?.label || name}</span>
                            <span className="font-medium tabular-nums text-[color:var(--aqt-fg)] ml-2">{label}</span>
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

export function RankHistorySkeleton({ className }: Readonly<{ className?: string }>) {
  return (
    <div className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center gap-3">
        <Skeleton className="w-[130px] h-8 bg-[color:var(--aqt-overlay-2)]" />
        <Skeleton className="w-[170px] h-8 bg-[color:var(--aqt-overlay-2)]" />
      </div>
      <div className={CARD_CLASS}>
        <Skeleton className="h-[180px] w-full bg-[color:var(--aqt-overlay-1)]" />
      </div>
    </div>
  );
}
