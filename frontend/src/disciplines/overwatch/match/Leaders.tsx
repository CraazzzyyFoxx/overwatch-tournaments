"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { LEADER_STATS, STAT_META, findLeader, formatStat, type MatchStatsTeam } from "./stats";
import { CatalogEntityStrip } from "@/components/catalog/CatalogEntityImage";
import { Card } from "@/components/ui/card";
import { Eyebrow } from "@/components/ui/eyebrow";
import PlayerName from "@/components/PlayerName";
import { cn } from "@/lib/utils";

interface LeadersProps {
  home: MatchStatsTeam;
  away: MatchStatsTeam;
  round: number;
  /** Column overrides for a narrower host than the full-width match page. */
  gridClassName?: string;
}

const Leaders = ({ home, away, round, gridClassName }: LeadersProps) => {
  const t = useTranslations<never>();
  const format = useFormatter();

  const cards = LEADER_STATS.map((name) => ({
    name,
    leader: findLeader(home, away, round, name)
  })).filter((entry) => entry.leader !== null);

  if (cards.length === 0) return null;

  return (
    <div>
      <Eyebrow className="aqt-tnum mb-2 block">{t("matches.leaders.title")}</Eyebrow>
      <div className={cn("grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6", gridClassName)}>
        {cards.map(({ name, leader }) => {
          if (!leader) return null;
          const accent = leader.side === "home" ? "var(--aqt-teal)" : "var(--aqt-rose)";
          const heroes = leader.player.heroes[round] ?? [];
          return (
            <Card
              key={name}
              className="flex flex-col gap-2 p-3"
              style={{ borderLeft: `3px solid ${accent}` }}
            >
              <Eyebrow tone="dim">{t((STAT_META[name]?.labelKey ?? name) as Parameters<typeof t>[0])}</Eyebrow>
              <span className="aqt-tnum text-title font-bold leading-none text-[color:var(--aqt-fg)]">
                {formatStat(name, leader.value, format)}
              </span>
              <div className="mt-auto flex items-center gap-2">
                <CatalogEntityStrip entities={heroes} size="sm" limit={2} />
                <div className="min-w-0" style={{ color: accent }}>
                  <PlayerName display={leader.player.display} tag="hidden" className="text-label" />
                </div>
              </div>
            </Card>
          );
        })}
      </div>
    </div>
  );
};

export default Leaders;
