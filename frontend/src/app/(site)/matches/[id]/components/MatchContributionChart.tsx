"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell
} from "recharts";
import { TeamWithStats } from "@/types/team.types";
import { LogStatsName } from "@/types/stats.types";
import { STAT_META, activePlayers, formatStat, playerStat } from "@/utils/matchStats";

interface MatchContributionChartProps {
  home: TeamWithStats;
  away: TeamWithStats;
  round: number;
}

// Metrics worth comparing per-player as a distribution across the lobby.
const METRICS: LogStatsName[] = [
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked,
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.DamageTaken
];

interface Datum {
  /** Player row id — the cell key: `data` is re-sorted whenever the metric
   *  changes, so a positional key would leave each bar's colour behind. */
  id: number;
  name: string;
  value: number;
  side: "home" | "away";
}

const MatchContributionChart = ({ home, away, round }: MatchContributionChartProps) => {
  const t = useTranslations<never>();
  const format = useFormatter();
  const [metric, setMetric] = useState<LogStatsName>(LogStatsName.HeroDamageDealt);

  const data: Datum[] = [
    ...activePlayers(home, round).map((player) => ({
      id: player.id,
      name: player.name.split("#")[0],
      value: playerStat(player, round, metric),
      side: "home" as const
    })),
    ...activePlayers(away, round).map((player) => ({
      id: player.id,
      name: player.name.split("#")[0],
      value: playerStat(player, round, metric),
      side: "away" as const
    }))
  ].sort((a, b) => b.value - a.value);

  if (data.length === 0) return null;

  const chartHeight = Math.max(220, data.length * 30 + 24);

  return (
    <div className="rounded-[12px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="aqt-tnum text-label font-bold uppercase tracking-label text-[color:var(--aqt-fg-faint)]">
          {t("matches.contribution.title")}
        </span>
        <div className="flex flex-wrap gap-1.5">
          {METRICS.map((name) => {
            const active = name === metric;
            return (
              <button
                key={name}
                type="button"
                onClick={() => setMetric(name)}
                className="rounded-md border px-2.5 py-1 text-label font-semibold transition-colors"
                style={{
                  borderColor: active ? "color-mix(in srgb, var(--aqt-teal) 35%, transparent)" : "var(--aqt-border)",
                  background: active ? "color-mix(in srgb, var(--aqt-teal) 12%, transparent)" : "var(--aqt-overlay-2)",
                  color: active ? "var(--aqt-teal)" : "var(--aqt-fg-muted)"
                }}
              >
                {t((STAT_META[name]?.labelKey ?? name) as Parameters<typeof t>[0])}
              </button>
            );
          })}
        </div>
      </div>
      <div style={{ height: chartHeight }} className="w-full">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, left: 8, bottom: 4 }}>
            <CartesianGrid horizontal={false} strokeDasharray="3 3" opacity={0.15} />
            <XAxis
              type="number"
              tick={{ fill: "var(--aqt-fg-muted)", fontSize: 11 }}
              tickFormatter={(value: number) => formatStat(metric, value, format)}
            />
            <YAxis
              type="category"
              dataKey="name"
              width={110}
              tick={{ fill: "var(--aqt-fg-muted)", fontSize: 11 }}
            />
            <Tooltip
              cursor={{ fill: "var(--aqt-overlay-3)" }}
              contentStyle={{
                backgroundColor: "var(--aqt-card-2)",
                border: "1px solid var(--aqt-border-2)",
                borderRadius: 8,
                color: "var(--aqt-fg)"
              }}
              // Recharts colours each item with `entry.color || '#000'`; the bar's
              // fill lives on <Cell>, not <Bar>, so items default to black on the
              // dark surface. Force readable colours on both label and items.
              labelStyle={{ color: "var(--aqt-fg)", fontWeight: 600, marginBottom: 2 }}
              itemStyle={{ color: "var(--aqt-fg)" }}
              formatter={(value: number) => [
                formatStat(metric, value, format),
                t((STAT_META[metric]?.labelKey ?? metric) as Parameters<typeof t>[0])
              ]}
            />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}>
              {data.map((datum) => (
                <Cell
                  key={datum.id}
                  fill={datum.side === "home" ? "var(--aqt-teal)" : "var(--aqt-rose)"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
};

export default MatchContributionChart;
