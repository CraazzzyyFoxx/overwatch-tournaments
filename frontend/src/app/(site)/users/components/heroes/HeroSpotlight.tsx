"use client";

import React from "react";
import { HeroWithUserStats } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";
import type { AqtRoleKey } from "@/app/(site)/users/components/shared/atoms";
import HeroImage from "@/components/hero/HeroImage";
import { formatDelta, formatSeconds } from "@/app/(site)/users/components/heroes/utils";

// Quick-stats shown in the spotlight (first 3 present, in this order).
export const QUICK_CANDIDATES: LogStatsName[] = [
  LogStatsName.Winrate,
  LogStatsName.KDA,
  LogStatsName.HeroDamageDealt,
  LogStatsName.Eliminations
];

export const QUICK_LABELS: Partial<Record<LogStatsName, string>> = {
  [LogStatsName.Winrate]: "Winrate",
  [LogStatsName.KDA]: "KDA",
  [LogStatsName.HeroDamageDealt]: "Dmg/10",
  [LogStatsName.Eliminations]: "Elims/10"
};

export interface QuickStatData {
  name: LogStatsName;
  label: string;
  value: string;
  delta: number | null;
}

export interface SpotlightHero {
  hero: HeroWithUserStats;
  playtime: number;
  share: number;
}

const QuickStat = ({ label, value, delta }: { label: string; value: string; delta: number | null }) => (
  <div className="flex flex-col items-end gap-0.5">
    <span className="text-[10.5px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">{label}</span>
    <span className="aqt-display text-[28px] font-bold leading-none">{value}</span>
    {delta != null ? (
      <span
        className="aqt-mono text-[11.5px] font-bold"
        style={{ color: delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
      >
        {formatDelta(delta)}
      </span>
    ) : null}
  </div>
);

const HeroSpotlight = ({
  selected,
  heroVariant,
  quickStats
}: {
  selected: SpotlightHero;
  heroVariant: AqtRoleKey;
  quickStats: QuickStatData[];
}) => (
  <div
    className="relative grid grid-cols-[auto_1fr_auto] items-center gap-6 overflow-hidden rounded-xl border p-5"
    style={{
      background: `linear-gradient(135deg, color-mix(in srgb, var(--aqt-${heroVariant}) 18%, transparent), color-mix(in srgb, var(--aqt-${heroVariant}) 4%, transparent))`,
      borderColor: `color-mix(in srgb, var(--aqt-${heroVariant}) 25%, transparent)`
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
          className="aqt-mono inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[12px] uppercase tracking-[0.06em]"
          style={{ background: `var(--aqt-${heroVariant})`, color: "var(--aqt-bg)" }}
        >
          {selected.hero.hero.type ?? selected.hero.hero.role}
        </span>
        <span className="aqt-mono text-[13px] text-[color:var(--aqt-fg-muted)]">
          {formatSeconds(selected.playtime, { withSeconds: false })} played
        </span>
        <span
          className="aqt-mono inline-flex items-center gap-1.5 rounded-md border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_100%/0.06)] px-2 py-0.5 text-[12px]"
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
);

export default HeroSpotlight;
