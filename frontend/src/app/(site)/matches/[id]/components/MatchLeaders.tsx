"use client";

import React from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { TeamWithStats } from "@/types/team.types";
import { LEADER_STATS, STAT_META, findLeader, formatStat } from "@/utils/matchStats";
import { HeroStrip } from "@/components/hero/HeroImage";
import { getPlayerSlug } from "@/utils/player";

interface MatchLeadersProps {
  home: TeamWithStats;
  away: TeamWithStats;
  round: number;
}

const MatchLeaders = ({ home, away, round }: MatchLeadersProps) => {
  const t = useTranslations<never>();

  const cards = LEADER_STATS.map((name) => ({ name, leader: findLeader(home, away, round, name) })).filter(
    (entry) => entry.leader !== null
  );

  if (cards.length === 0) return null;

  return (
    <div>
      <span className="aqt-mono mb-2 block text-[10px] font-bold uppercase tracking-[0.14em] text-[color:var(--aqt-fg-faint)]">
        {t("matches.leaders.title")}
      </span>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
        {cards.map(({ name, leader }) => {
          if (!leader) return null;
          const accent = leader.side === "home" ? "var(--aqt-teal)" : "var(--aqt-rose)";
          const displayName = leader.player.name.split("#")[0];
          const heroes = leader.player.heroes[round] ?? [];
          return (
            <div
              key={name}
              className="flex flex-col gap-2 rounded-[10px] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] p-3"
              style={{ borderLeft: `3px solid ${accent}` }}
            >
              <span className="text-[10px] font-semibold uppercase tracking-[0.06em] text-[color:var(--aqt-fg-dim)]">
                {t((STAT_META[name]?.labelKey ?? name) as Parameters<typeof t>[0])}
              </span>
              <span className="aqt-tnum text-[22px] font-bold leading-none text-[color:var(--aqt-fg)]">
                {formatStat(name, leader.value)}
              </span>
              <div className="mt-auto flex items-center gap-2">
                <HeroStrip heroes={heroes} size="sm" limit={2} />
                <Link
                  href={`/users/${getPlayerSlug(leader.player.name)}`}
                  className="truncate text-[12px] font-semibold hover:underline"
                  style={{ color: accent }}
                  title={displayName}
                >
                  {displayName}
                </Link>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default MatchLeaders;
