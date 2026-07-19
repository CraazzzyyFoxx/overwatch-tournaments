"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { LogStatsName } from "@/types/stats.types";
import { getHumanizedStats } from "@/utils/stats";

export const RADAR_STATS: LogStatsName[] = [
  LogStatsName.HeroDamageDealt,
  LogStatsName.Eliminations,
  LogStatsName.CriticalHits,
  LogStatsName.Deaths,
  LogStatsName.HealingDealt
];

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

export interface RadarPoint {
  stat: LogStatsName;
  you: number;
  global: number;
}

const HeroRadar = ({ radarData }: { radarData: RadarPoint[] | null }) => {
  const t = useTranslations();

  // Terse radar axis label per stat (falls back to the humanized stat name).
  const axisLabel = (stat: LogStatsName): string => {
    switch (stat) {
      case LogStatsName.HeroDamageDealt:
        return t("users.heroes.radar.dmg");
      case LogStatsName.Eliminations:
        return t("users.heroes.radar.elims");
      case LogStatsName.CriticalHits:
        return t("users.heroes.radar.crits");
      case LogStatsName.Deaths:
        return t("users.heroes.radar.surv");
      case LogStatsName.HealingDealt:
        return t("users.heroes.radar.heal");
      default:
        return getHumanizedStats(stat);
    }
  };

  return (
  <div className="flex flex-col items-center gap-2">
    {radarData ? (
      <svg viewBox="-130 -130 260 260" width="240" height="240" className="block">
        {[100, 75, 50, 25].map((r) => (
          <polygon
            key={r}
            className="aqt-radar-grid"
            points={radarPolygon(radarData.map(() => r / 100), 100)}
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
              {axisLabel(d.stat)}
            </text>
          );
        })}
      </svg>
    ) : null}
    <div className="flex gap-3.5 pt-1.5 text-[12px] text-[color:var(--aqt-fg-muted)]">
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "var(--aqt-teal)" }} />
        {t("users.heroes.you")}
      </span>
      <span className="inline-flex items-center gap-1.5">
        <span className="h-2.5 w-2.5 rounded-sm" style={{ background: "hsl(220 12% 55%)" }} />
        {t("users.heroes.globalAvg")}
      </span>
    </div>
  </div>
  );
};

export default HeroRadar;
