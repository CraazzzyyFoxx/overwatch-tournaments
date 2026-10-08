"use client";

import { useTranslations } from "next-intl";
import { CardSurface } from "@/app/(site)/users/components/shared/atoms";
import { winrateColor } from "@/app/(site)/users/components/heroes/utils";

interface HeroMapRow {
  id: number;
  name: string;
  mode: string;
  winRate: number;
  win: number;
  loss: number;
}

const MapsForHero = ({ heroName, heroMaps }: { heroName: string; heroMaps: HeroMapRow[] }) => {
  const t = useTranslations();
  return (
    <CardSurface
      flush
      title={t("users.heroes.mapsFor", { hero: heroName })}
      subtitle={heroMaps.length > 0 ? t("users.heroes.mapsSubtitle", { count: heroMaps.length }) : undefined}
    >
      {heroMaps.length > 0 ? (
        <div className="max-h-[360px] overflow-y-auto">
          {heroMaps.map((m) => {
            const wr = m.winRate * 100;
            return (
              <div
                key={m.id}
                className="grid grid-cols-[1fr_auto_auto] items-center gap-3 border-b border-[color:var(--aqt-border)] px-4 py-2.5 last:border-b-0"
              >
                <div className="flex min-w-0 flex-col">
                  <span className="truncate text-body font-medium text-[color:var(--aqt-fg)]">{m.name}</span>
                  <span className="truncate text-label text-[color:var(--aqt-fg-dim)]">{m.mode}</span>
                </div>
                <span
                  className="aqt-tnum text-right text-caption font-bold"
                  style={{ color: winrateColor(wr) }}
                >
                  {wr.toFixed(0)}%
                </span>
                <span className="aqt-tnum text-right text-caption text-[color:var(--aqt-fg-muted)]">
                  {m.win}-{m.loss}
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="py-6 text-center text-caption text-[color:var(--aqt-fg-dim)]">
          {t("users.heroes.noMapData")}
        </div>
      )}
    </CardSurface>
  );
};

export default MapsForHero;
