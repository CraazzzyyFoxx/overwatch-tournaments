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
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import { FilterChip, FilterChipGroup } from "@/components/ui/filter-chip";
import { splitHandle } from "@/lib/player";
import { LogStatsName } from "../stat-names";
import { STAT_META, activePlayers, formatStat, playerStat, type MatchStatsTeam } from "./stats";

interface ContributionChartProps {
  home: MatchStatsTeam;
  away: MatchStatsTeam;
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
  /** Participation/member identity survives metric re-sorting and roster changes. */
  id: string;
  name: string;
  value: number;
  side: "home" | "away";
}

const ContributionChart = ({ home, away, round }: ContributionChartProps) => {
  const t = useTranslations<never>();
  const format = useFormatter();
  const [metric, setMetric] = useState<LogStatsName>(LogStatsName.HeroDamageDealt);

  const data: Datum[] = [
    ...activePlayers(home, round).map((player) => ({
      id: `${home.id}:${player.workspace_member_id}`,
      name: splitHandle(player.name).name,
      value: playerStat(player, round, metric),
      side: "home" as const
    })),
    ...activePlayers(away, round).map((player) => ({
      id: `${away.id}:${player.workspace_member_id}`,
      name: splitHandle(player.name).name,
      value: playerStat(player, round, metric),
      side: "away" as const
    }))
  ].sort((a, b) => b.value - a.value);

  if (data.length === 0) return null;

  const chartHeight = Math.max(220, data.length * 30 + 24);

  return (
    <Card className="p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <Eyebrow className="aqt-tnum">{t("matches.contribution.title")}</Eyebrow>
        <FilterChipGroup label={t("matches.contribution.title")}>
          {METRICS.map((name) => (
            <FilterChip key={name} active={name === metric} onClick={() => setMetric(name)}>
              {t((STAT_META[name]?.labelKey ?? name) as Parameters<typeof t>[0])}
            </FilterChip>
          ))}
        </FilterChipGroup>
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
    </Card>
  );
};

export default ContributionChart;
