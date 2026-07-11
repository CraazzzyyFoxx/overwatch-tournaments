"use client";

import React from "react";
import { useTranslations } from "next-intl";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer
} from "recharts";
import { TeamWithStats } from "@/types/team.types";
import { LogStatsName } from "@/types/stats.types";

interface MatchStatsChartProps {
  homeTeam: TeamWithStats;
  awayTeam: TeamWithStats;
  matchRound: number;
}

const MatchStatsChart = ({ homeTeam, awayTeam, matchRound }: MatchStatsChartProps) => {
  const t = useTranslations();
  const data = [
    ...homeTeam.players.map((p) => ({
      name: p.name,
      team: homeTeam.name,
      Kills: p.stats?.[matchRound]?.[LogStatsName.Eliminations] || 0,
      Assists: p.stats?.[matchRound]?.[LogStatsName.Assists] || 0
    })),
    ...awayTeam.players.map((p) => ({
      name: p.name,
      team: awayTeam.name,
      Kills: p.stats?.[matchRound]?.[LogStatsName.Eliminations] || 0,
      Assists: p.stats?.[matchRound]?.[LogStatsName.Assists] || 0
    }))
  ];

  return (
    <div className="h-[400px] w-full mt-8">
      <h3 className="text-xl font-semibold mb-4 text-center">{t("encounters.chart.title")}</h3>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart
          data={data}
          margin={{
            top: 20,
            right: 30,
            left: 20,
            bottom: 50
          }}
        >
          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
          <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} tick={{ fill: 'hsl(var(--foreground))' }} />
          <YAxis tick={{ fill: 'hsl(var(--foreground))' }} />
          <Tooltip
            contentStyle={{ backgroundColor: "hsl(var(--popover))", borderColor: "hsl(var(--border))", color: "hsl(var(--foreground))" }}
            itemStyle={{ color: "hsl(var(--foreground))" }}
            cursor={{ fill: 'hsl(var(--muted))' }}
          />
          <Legend verticalAlign="top" wrapperStyle={{ paddingBottom: '20px' }} />
          <Bar
            dataKey="Kills"
            name={t("encounters.chart.kills")}
            fill="hsl(var(--chart-1))"
            radius={[4, 4, 0, 0]}
          />
          <Bar
            dataKey="Assists"
            name={t("encounters.chart.assists")}
            fill="hsl(var(--chart-5))"
            radius={[4, 4, 0, 0]}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

export default MatchStatsChart;
