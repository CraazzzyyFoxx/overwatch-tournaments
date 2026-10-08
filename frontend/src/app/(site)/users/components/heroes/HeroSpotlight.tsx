"use client";

import { useTranslations } from "next-intl";
import { HeroWithUserStats } from "@/types/hero.types";
import { LogStatsName } from "@/types/stats.types";
import type { AqtRoleKey } from "@/lib/roster/player-role";
import HeroImage from "@/components/hero/HeroImage";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { CardSurface, ProfileStat } from "@/app/(site)/users/components/shared/atoms";
import { formatSeconds } from "@/lib/format";
import { formatDelta } from "@/app/(site)/users/components/heroes/utils";

// Quick-stats shown in the spotlight (first 4 present, in this order).
export const QUICK_CANDIDATES: LogStatsName[] = [
  LogStatsName.Winrate,
  LogStatsName.KDA,
  LogStatsName.HeroDamageDealt,
  LogStatsName.Eliminations
];

interface QuickStatData {
  name: LogStatsName;
  label: string;
  value: string;
  delta: number | null;
}

interface SpotlightHero {
  hero: HeroWithUserStats;
  playtime: number;
  share: number;
}

/** Canonical English role names used ONLY to pick the PlayerRoleIcon glyph. */
const ROLE_ICON_NAME: Record<AqtRoleKey, string> = {
  tank: "Tank",
  damage: "Damage",
  support: "Support"
};

const HeroSpotlight = ({
  selected,
  heroVariant,
  quickStats
}: {
  selected: SpotlightHero;
  heroVariant: AqtRoleKey;
  quickStats: QuickStatData[];
}) => {
  const t = useTranslations();
  const roleName = selected.hero.hero.type ?? selected.hero.hero.role;
  return (
    <CardSurface>
      <div className="flex flex-col gap-6">
        <div className="flex items-center gap-4">
          <HeroImage hero={selected.hero.hero} size={80} rounded="lg" />
          <div className="flex min-w-0 flex-col gap-1.5">
            <h2 className="aqt-display m-0 truncate text-headline font-bold leading-tight text-[color:var(--aqt-fg)]">
              {selected.hero.hero.name}
            </h2>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-caption text-[color:var(--aqt-fg-muted)]">
              <span className="inline-flex items-center gap-1.5">
                <PlayerRoleIcon
                  role={ROLE_ICON_NAME[heroVariant]}
                  size={14}
                  color={`var(--aqt-${heroVariant})`}
                  decorative
                />
                <span className="capitalize">{roleName}</span>
              </span>
              <span className="aqt-tnum">{t("users.heroes.played", { time: formatSeconds(selected.playtime) })}</span>
              <span className="aqt-tnum">
                {t("users.heroes.poolShare", { pct: (selected.share * 100).toFixed(0) })}
              </span>
            </div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-x-6 gap-y-5 sm:grid-cols-4">
          {quickStats.length > 0 ? (
            quickStats.map((qs) => (
              <ProfileStat key={qs.name} label={qs.label} value={qs.value}>
                {qs.delta == null ? null : (
                  <span
                    className="aqt-tnum text-label font-bold"
                    style={{ color: qs.delta >= 0 ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                  >
                    {formatDelta(qs.delta)}
                  </span>
                )}
              </ProfileStat>
            ))
          ) : (
            <ProfileStat
              label={t("users.heroes.playtimeShare")}
              value={`${(selected.share * 100).toFixed(0)}%`}
            />
          )}
        </div>
      </div>
    </CardSurface>
  );
};

export default HeroSpotlight;
