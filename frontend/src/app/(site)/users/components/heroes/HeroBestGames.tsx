"use client";

import React from "react";
import Image from "next/image";
import Link from "next/link";
import { Crown, Trophy } from "lucide-react";
import { LogStatsName } from "@/types/stats.types";
import type { HeroBestStat, HeroWithUserStats } from "@/types/hero.types";
import { getHumanizedStats } from "@/utils/stats";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { formatStatValue } from "@/app/(site)/users/components/heroes/utils";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from "@/components/ui/tooltip";

// Per-game "personal record" stats (higher = better) worth showcasing.
const RECORD_STATS: LogStatsName[] = [
  LogStatsName.Eliminations,
  LogStatsName.FinalBlows,
  LogStatsName.HeroDamageDealt,
  LogStatsName.HealingDealt,
  LogStatsName.DamageBlocked,
  LogStatsName.SoloKills
];

interface Record {
  name: LogStatsName;
  best: HeroBestStat;
  /** The player's best is also the all-players best for this hero+stat. */
  isGlobalRecord: boolean;
}

/** Career-best single-game performances for the selected hero, built from
 *  `HeroStat.best`. Each record links to the encounter where it happened and
 *  shows the map/tournament on hover; a crown marks an all-time (global) best. */
const HeroBestGames = ({ hero }: { hero: HeroWithUserStats }) => {
  const records: Record[] = RECORD_STATS.map((name) => {
    const stat = hero.stats.find((s) => s.name === name);
    if (!stat || !stat.best || !Number.isFinite(stat.best.value) || stat.best.value <= 0) return null;
    return {
      name,
      best: stat.best,
      isGlobalRecord: stat.best_all != null && stat.best.value >= stat.best_all.value
    };
  }).filter((r): r is Record => r !== null);

  if (records.length === 0) return null;

  return (
    <CardSurface title="Career-best games" icon={<Trophy size={15} />} subtitle={`${hero.hero.name} · personal records`}>
      <TooltipProvider delayDuration={120}>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {records.map(({ name, best, isGlobalRecord }) => (
            <Tooltip key={name}>
              <TooltipTrigger asChild>
                <Link
                  href={`/encounters/${best.encounter_id}`}
                  className="flex flex-col gap-1 rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.018)] px-3 py-2.5 transition-colors hover:border-[color:var(--aqt-border-2)] hover:bg-[hsl(0_0%_100%/0.04)]"
                >
                  <span className="flex items-center gap-1.5 text-[10.5px] font-bold uppercase tracking-[0.12em] text-[color:var(--aqt-fg-faint)]">
                    {getHumanizedStats(name)}
                    {isGlobalRecord ? <Crown className="h-3 w-3" style={{ color: "var(--aqt-amber)" }} aria-label="All-time best" /> : null}
                  </span>
                  <span className="aqt-display text-[24px] font-bold leading-none text-[color:var(--aqt-fg)]">
                    {formatStatValue(name, best.value)}
                  </span>
                  <span className="aqt-mono truncate text-[11px] text-[color:var(--aqt-fg-dim)]">
                    {best.map_name} · {best.tournament_name}
                  </span>
                </Link>
              </TooltipTrigger>
              <TooltipContent className="w-60 overflow-hidden p-0">
                {best.map_image_path ? (
                  <div className="relative h-24 w-full">
                    <Image src={best.map_image_path} alt={best.map_name} fill sizes="240px" className="object-cover" />
                  </div>
                ) : null}
                <div className="flex flex-col gap-0.5 px-3 py-2">
                  <span className="text-[13px] font-semibold">{best.tournament_name}</span>
                  <span className="aqt-mono text-[12px] opacity-80">{best.map_name}</span>
                </div>
              </TooltipContent>
            </Tooltip>
          ))}
        </div>
      </TooltipProvider>
    </CardSurface>
  );
};

export default HeroBestGames;
