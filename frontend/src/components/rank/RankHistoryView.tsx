"use client";

import { useMemo, useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Compass, LineChart as ChartIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { CartesianGrid, Line, LineChart, XAxis, YAxis } from "recharts";

import { ChartEmptyState, RankHistorySkeleton } from "@/components/RankHistoryState";
import { Card } from "@/components/ui/card";
import {
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig
} from "@/components/ui/chart";
import Image from "@/components/ui/image";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import type { SlotProps } from "@/disciplines/types";
import { useDisciplineMetadata } from "@/hooks/useDisciplineMetadata";
import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import { useUserRankHistory } from "@/hooks/useRankHistory";
import { useFormatter } from "@/lib/datetime/client";
import { userQueryKeys } from "@/lib/users/query-keys";
import rankService from "@/services/rank.service";
import type { NativeTier } from "@/types/discipline.types";
import type { CurrentRank, RankSeries } from "@/types/rank.types";

import {
  PERIODS,
  bestCurrent,
  chartRows,
  dimensionOf,
  isLone,
  periodStart,
  rankAxis,
  tierAt,
  type Period
} from "./rank-history-model";

type GroupBy = "dimension" | "account";

// Categorical series palette. The five shadcn chart tokens hold bare HSL triplets, so they are wrapped in `hsl()`;
// the sixth slot borrows an existing accent rather than inventing a `--chart-6`.
const PALETTE = [
  "hsl(var(--chart-1))",
  "hsl(var(--chart-2))",
  "hsl(var(--chart-3))",
  "hsl(var(--chart-4))",
  "hsl(var(--chart-5))",
  "var(--aqt-blue)"
];

/** The queues a collector reports (League's Solo/Duo and Flex); roles name themselves through the game's metadata. */
const QUEUES = ["solo", "flex"] as const;

/** What recharts hands a `dot` render function: the point's place among every point of its line. */
type DotArgs = { key: string; index: number; cx: number; cy: number; points: ReadonlyArray<{ value?: number | null }> };

/**
 * Rank history of one player in one game, the `rankHistory` slot of every game that collects ranks: the current rank
 * per line (role / queue / the one rank) as an emblem, then those lines over time. Everything game-specific comes
 * from the data: lines from the series' `role`/`queue`, rank names and emblems from the game's native ladder.
 */
export default function RankHistoryView({
  userId,
  axis,
  discipline,
  framed = true
}: Readonly<SlotProps["rankHistory"]>) {
  const t = useTranslations("rankHistory");
  const [period, setPeriod] = useLocalStorageState<Period>("rank-history-period", "3m");
  const dateFrom = useMemo(() => periodStart(period), [period]);
  const metadata = useDisciplineMetadata(axis, discipline);
  const current = useQuery({
    queryKey: userQueryKeys.rankCurrent(userId, discipline),
    queryFn: () => rankService.getUserCurrentRanks(userId, discipline)
  });
  // Daily: Overwatch fills each day from the last known rank; the other collectors return their changes as-is.
  const history = useUserRankHistory(userId, { discipline, granularity: "daily", dateFrom });

  if (metadata.isLoading || current.isLoading || history.isLoading) return <RankHistorySkeleton framed={framed} />;
  if (metadata.isError || current.isError || history.isError) {
    return (
      <ChartEmptyState icon={AlertCircle} tone="error" title={t("errorTitle")} body={t("errorBody")} framed={framed} />
    );
  }
  return (
    <RankHistoryBody
      ladder={metadata.data?.native_ladder ?? []}
      roles={metadata.data?.roles ?? []}
      ranks={current.data?.ranks ?? []}
      series={history.data?.series ?? []}
      period={period}
      onPeriodChange={setPeriod}
      framed={framed}
    />
  );
}

/** The chart's own box and its corner glows; nothing inside a card that already frames the chart. */
function ChartFrame({ framed, children }: Readonly<{ framed: boolean; children: ReactNode }>) {
  if (!framed) return children;
  return (
    <Card className="relative overflow-hidden p-4 backdrop-blur-xs">
      <div className="pointer-events-none absolute -left-12 -top-12 -z-10 size-24 rounded-full bg-primary/5 blur-2xl" />
      <div className="pointer-events-none absolute -bottom-12 -right-12 -z-10 size-24 rounded-full bg-primary/5 blur-2xl" />
      {children}
    </Card>
  );
}

function RankHistoryBody({
  ladder,
  roles,
  ranks,
  series,
  period,
  onPeriodChange,
  framed
}: Readonly<{
  ladder: NativeTier[];
  roles: readonly { code: string; name: string }[];
  ranks: CurrentRank[];
  series: RankSeries[];
  period: Period;
  onPeriodChange: (period: Period) => void;
  framed: boolean;
}>) {
  const t = useTranslations("rankHistory");
  const format = useFormatter();
  const [platformChoice, setPlatform] = useState<string | null>(null);
  const [groupByChoice, setGroupBy] = useState<GroupBy>("dimension");
  const [accountChoice, setAccount] = useState<number | null>(null);
  const [dimensionChoice, setDimension] = useState<string | null>(null);

  // Lines read in the game's role order, then the queue order; anything else after, as it came.
  const order: string[] = [...roles.map((role) => role.code), ...QUEUES];
  const rankOf = (dimension: string) => (order.includes(dimension) ? order.indexOf(dimension) : order.length);
  const byRole = series.some((line) => line.role != null) || ranks.some((rank) => rank.role != null);
  const dimensionLabel = (dimension: string | null) => {
    if (dimension == null) return t("current");
    const role = roles.find((candidate) => candidate.code === dimension);
    if (role) return role.name;
    const queue = QUEUES.find((code) => code === dimension);
    return queue ? t(`queue.${queue}`) : dimension;
  };

  const platforms = [...new Set([...series, ...ranks].flatMap((row) => (row.platform ? [row.platform] : [])))];
  const platform =
    platformChoice != null && platforms.includes(platformChoice)
      ? platformChoice
      : platforms.includes("pc")
        ? "pc"
        : (platforms[0] ?? null);
  const platformSeries = series.filter((line) => (line.platform ?? null) === platform);

  const accounts = [
    ...new Map(platformSeries.map((line) => [line.social_account_id, line.handle] as const)).entries()
  ].map(([id, handle]) => ({ id, handle }));
  const dimensions = [
    ...new Set(platformSeries.map(dimensionOf).filter((value): value is string => value != null))
  ].sort((a, b) => rankOf(a) - rankOf(b));
  // Grouping is a choice only with both roles/queues and several accounts; a game with neither (Deadlock) draws a
  // line per account, a lone account a line per role/queue.
  const canRegroup = dimensions.length > 0 && accounts.length > 1;
  const groupBy: GroupBy = canRegroup ? groupByChoice : dimensions.length > 0 ? "dimension" : "account";
  const accountId = accounts.find((account) => account.id === accountChoice)?.id ?? accounts[0]?.id;
  const dimension = dimensionChoice != null && dimensions.includes(dimensionChoice) ? dimensionChoice : dimensions[0];

  const active =
    groupBy === "dimension"
      ? platformSeries
          .filter((line) => line.social_account_id === accountId)
          .sort((a, b) => rankOf(dimensionOf(a) ?? "") - rankOf(dimensionOf(b) ?? ""))
      : platformSeries.filter((line) => dimensionOf(line) === (dimension ?? null));
  const lines = active.map((line, i) => {
    const own = dimensionOf(line);
    const color = PALETTE[i % PALETTE.length];
    return {
      key: `line${i}`,
      label: groupBy === "dimension" ? dimensionLabel(own) : line.handle,
      // A role or queue with a design-book hue (`--aqt-tank`, `--aqt-flex`…) keeps it; the rest take the palette.
      color: groupBy === "dimension" && own ? `var(--aqt-${own}, ${color})` : color,
      series: line
    };
  });
  const rows = chartRows(lines);
  const config = Object.fromEntries(lines.map((line) => [line.key, { label: line.label, color: line.color }])) satisfies ChartConfig;

  const best = bestCurrent(ranks, platform);
  const heroDimensions = [
    ...new Set([...ranks.filter((rank) => (rank.platform ?? null) === platform), ...platformSeries].map(dimensionOf))
  ].sort((a, b) => rankOf(a ?? "") - rankOf(b ?? ""));
  const multiAccount = new Set(ranks.map((rank) => rank.social_account_id)).size > 1;

  // Daily points are stamped at their UTC day, so dates read in UTC.
  const day = (at: number, style: "short" | "medium") =>
    format.dateTime(new Date(at), style === "short" ? { month: "short", day: "numeric", timeZone: "UTC" } : { dateStyle: "medium", timeZone: "UTC" });

  return (
    <div className="@container space-y-3">
      <dl className="grid grid-cols-1 gap-2 @lg:auto-cols-fr @lg:grid-flow-col">
        {(heroDimensions.length > 0 ? heroDimensions : [null]).map((key) => {
          const rank = best.get(key);
          const ranked = rank?.is_ranked && rank.rank_value != null ? rank : undefined;
          const tier = tierAt(ladder, ranked?.rank_value);
          const details = [
            ranked?.lp != null ? t("lp", { lp: ranked.lp }) : null,
            ranked?.wins != null && ranked.losses != null ? t("record", { wins: ranked.wins, losses: ranked.losses }) : null
          ].filter(Boolean);
          const content = (
            <>
              {tier ? (
                <Image
                  src={tier.icon_url}
                  alt=""
                  aria-hidden
                  width={40}
                  height={40}
                  className="size-8 shrink-0 object-contain @3xl:size-10"
                />
              ) : (
                <div
                  aria-hidden
                  className="size-8 shrink-0 rounded-full border border-dashed border-[color:var(--aqt-border-2)] @3xl:size-10"
                />
              )}
              <div className="min-w-0">
                <dt className="truncate text-caption text-[color:var(--aqt-fg-dim)]">{dimensionLabel(key)}</dt>
                <dd className="truncate text-sm font-semibold tabular-nums text-[color:var(--aqt-fg)]">
                  {tier?.name ?? ranked?.division ?? t("unranked")}
                </dd>
                {details.length > 0 ? (
                  <dd className="text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">{details.join(" · ")}</dd>
                ) : null}
                {ranked && multiAccount ? (
                  <dd className="truncate text-caption text-[color:var(--aqt-fg-dim)]">{ranked.handle}</dd>
                ) : null}
              </div>
            </>
          );
          return framed ? (
            <Card key={key ?? "rank"} className="flex items-center gap-2 px-2.5 py-1.5">
              {content}
            </Card>
          ) : (
            <div key={key ?? "rank"} className="flex items-center gap-2">
              {content}
            </div>
          );
        })}
      </dl>

      <div className="flex flex-wrap items-center gap-3">
        {canRegroup ? (
          <Select value={groupBy} onValueChange={(value) => setGroupBy(value as GroupBy)}>
            <SelectTrigger aria-label={t("groupByLabel")} size="sm" className="w-[130px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="dimension">{byRole ? t("byRole") : t("byQueue")}</SelectItem>
              <SelectItem value="account">{t("byAccount")}</SelectItem>
            </SelectContent>
          </Select>
        ) : null}

        {groupBy === "dimension" && accounts.length > 1 ? (
          <Select value={accountId != null ? String(accountId) : undefined} onValueChange={(value) => setAccount(Number(value))}>
            <SelectTrigger aria-label={t("accountLabel")} size="sm" className="w-[170px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {accounts.map((account) => (
                <SelectItem key={account.id} value={String(account.id)}>
                  {account.handle}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}

        {groupBy === "account" && dimensions.length > 0 ? (
          <Select value={dimension} onValueChange={setDimension}>
            <SelectTrigger
              aria-label={byRole ? t("roleLabel") : t("queueLabel")}
              size="sm"
              className="w-[130px]"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {dimensions.map((value) => (
                <SelectItem key={value} value={value}>
                  {dimensionLabel(value)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}

        <Select value={period} onValueChange={(value) => onPeriodChange(value as Period)}>
          <SelectTrigger aria-label={t("periodLabel")} size="sm" className="w-[120px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {PERIODS.map((value) => (
              <SelectItem key={value} value={value}>
                {t(`period.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        {platforms.length > 1 && platform ? (
          <Select value={platform} onValueChange={setPlatform}>
            <SelectTrigger aria-label={t("platformLabel")} size="sm" className="w-[110px] uppercase">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {platforms.map((value) => (
                <SelectItem key={value} value={value} className="uppercase">
                  {value}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>

      {series.length === 0 ? (
        <ChartEmptyState icon={ChartIcon} title={t("emptyTitle")} body={t("emptyBody")} framed={framed} />
      ) : rows.length === 0 ? (
        <ChartEmptyState icon={Compass} title={t("noDataTitle")} body={t("noDataBody")} framed={framed} />
      ) : (
        <ChartFrame framed={framed}>
          <section aria-label={t("chartTitle")}>
            <ChartContainer config={config} className="aspect-auto h-[180px] w-full @lg:h-[220px]">
              <LineChart accessibilityLayer data={rows} margin={{ left: 2, right: 2, top: 4, bottom: 0 }}>
                {/* No `stroke`: recharts' `#ccc` default is what ChartContainer restyles to the themed border. */}
                <CartesianGrid vertical={false} strokeDasharray="3 3" />
                <XAxis
                  dataKey="at"
                  type="number"
                  scale="time"
                  domain={["dataMin", "dataMax"]}
                  tickLine={false}
                  axisLine={false}
                  tickMargin={6}
                  minTickGap={24}
                  tickFormatter={(value: number) => day(value, "short")}
                />
                <YAxis
                  tickLine={false}
                  axisLine={false}
                  width={96}
                  {...rankAxis(ladder, rows)}
                  tickFormatter={(value: number) => tierAt(ladder, value)?.name ?? String(value)}
                />
                <ChartTooltip
                  content={
                    <ChartTooltipContent
                      labelFormatter={(_, payload) => (payload[0] ? day(payload[0].payload.at, "medium") : null)}
                      formatter={(value, name, item) => (
                        <>
                          <div
                            aria-hidden
                            className="h-2.5 w-2.5 shrink-0 rounded-xs border"
                            style={{ backgroundColor: item.color, borderColor: item.color }}
                          />
                          <div className="flex flex-1 items-center justify-between gap-4 text-xs leading-none">
                            <span className="text-[color:var(--aqt-fg-muted)]">{config[name as string]?.label ?? name}</span>
                            <span className="ml-2 font-medium tabular-nums text-[color:var(--aqt-fg)]">
                              {tierAt(ladder, Number(value))?.name ?? String(value)}
                            </span>
                          </div>
                        </>
                      )}
                    />
                  }
                />
                {lines.map((line) => (
                  <Line
                    key={line.key}
                    dataKey={line.key}
                    name={line.key}
                    type="stepAfter"
                    stroke={`var(--color-${line.key})`}
                    strokeWidth={2.5}
                    dot={({ key, index, cx, cy, points }: DotArgs) =>
                      isLone(points, index) ? (
                        <circle key={key} cx={cx} cy={cy} r={3} fill={`var(--color-${line.key})`} />
                      ) : (
                        <g key={key} />
                      )
                    }
                    activeDot={{ r: 5, strokeWidth: 0 }}
                  />
                ))}
                <ChartLegend content={<ChartLegendContent className="pt-2" />} />
              </LineChart>
            </ChartContainer>
          </section>
        </ChartFrame>
      )}
    </div>
  );
}
