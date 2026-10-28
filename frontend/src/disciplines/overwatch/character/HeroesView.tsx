"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { CardSurface } from "@/components/profile/atoms";
import { SearchableImageSelect } from "@/components/ui/searchable-image-select";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import type { SlotProps } from "@/disciplines/types";
import { characterClass } from "@/lib/catalog/attrs";
import { LOW_SAMPLE_GAMES } from "@/lib/colors";
import type { CharacterWithUserStats } from "@/types/user.types";

import { LogStatsName } from "../stat-names";
import HeroBestGames from "./HeroBestGames";
import HeroRail, { type HeroRow } from "./HeroRail";
import HeroSpotlight from "./HeroSpotlight";
import HeroStatsTable from "./HeroStatsTable";
import HeroVsAverage from "./HeroVsAverage";
import MapsForHero from "./MapsForHero";
import { heroMapRows, overviewRows, radarAxes, recordRows, statRows } from "./hero-stats";
import { getOverall, heroWinrate, isRevertedStat } from "./utils";

type StatsView = "overview" | "all";

/**
 * Overwatch's characters tab (the profile's `characterStats` slot): the selected hero's band, its figures against
 * every player's on the hero, its records and its maps, with the hero rail beside them from `xl` up.
 */
const HeroesView = ({ characters, filterSlot, maps, retryMaps, metadata }: SlotProps["characterStats"]) => {
  const t = useTranslations();
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [view, setView] = useState<StatsView>("overview");

  // Most played first, each with its share of the player's time on every hero.
  const heroes = useMemo(() => {
    const byPlaytime = characters
      .map((hero) => ({ hero, playtime: getOverall(hero, LogStatsName.HeroTimePlayed) }))
      .sort((a, b) => b.playtime - a.playtime);
    const total = byPlaytime.reduce((sum, item) => sum + item.playtime, 0);
    return byPlaytime.map((item) => ({ ...item, share: total > 0 ? item.playtime / total : 0 }));
  }, [characters]);

  // A hero the tournament filter dropped falls back to the most played one.
  const selected = heroes.find((item) => item.hero.character.id === selectedId) ?? heroes[0];

  // One rail row per hero: the cross-hero comparison.
  const railRows = useMemo<HeroRow[]>(() => {
    const avg = (stats: CharacterWithUserStats["stats"], name: LogStatsName) => {
      const value = stats.find((s) => s.name === name)?.avg_10;
      return value != null && Number.isFinite(value) ? value : null;
    };
    return heroes.map(({ hero, playtime, share }) => {
      const winrate = heroWinrate(hero);
      let better = 0;
      let compared = 0;
      for (const s of hero.stats) {
        if (s.name === LogStatsName.HeroTimePlayed) continue;
        if (!Number.isFinite(s.avg_10) || !Number.isFinite(s.avg_10_all) || s.avg_10_all <= 0) continue;
        compared++;
        if (isRevertedStat(s.name) ? s.avg_10 < s.avg_10_all : s.avg_10 > s.avg_10_all) better++;
      }
      return {
        id: hero.character.id,
        hero: hero.character,
        role: characterClass(hero.character),
        playtime,
        share,
        winratePct: winrate == null ? null : winrate * 100,
        kda: avg(hero.stats, LogStatsName.KDA),
        dmg10: avg(hero.stats, LogStatsName.HeroDamageDealt),
        impact: compared > 0 ? better / compared : 0
      };
    });
  }, [heroes]);

  const rows = useMemo(() => (selected ? statRows(selected.hero) : []), [selected]);

  if (!selected) {
    return (
      <div className="aqt-player">
        <CardSurface action={filterSlot}>
          <p className="py-10 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroes.noStats")}</p>
        </CardSurface>
      </div>
    );
  }

  const heroId = selected.hero.character.id;
  const lowSampleNote =
    selected.hero.games < LOW_SAMPLE_GAMES ? t("users.heroes.lowSample", { count: LOW_SAMPLE_GAMES }) : null;
  const heroClass = characterClass(selected.hero.character);
  const records = recordRows(rows, heroClass);

  return (
    <div className="aqt-player flex flex-col gap-3.5">
      {/* Below xl the rail is hidden, so the hero is picked here. */}
      {heroes.length > 1 ? (
        <div className="w-full sm:w-60 xl:hidden">
          <SearchableImageSelect
            options={heroes.map(({ hero }) => ({
              value: String(hero.character.id),
              label: hero.character.name,
              imageSrc: hero.character.image_path
            }))}
            value={String(heroId)}
            onValueChange={(value) => {
              if (value) setSelectedId(Number(value));
            }}
            clearable={false}
            placeholder={t("users.heroes.pickHero")}
            ariaLabel={t("users.heroes.pickHero")}
            size="sm"
            triggerClassName="w-full"
          />
        </div>
      ) : null}
      <div className="grid grid-cols-1 gap-3.5 xl:grid-cols-[minmax(0,1fr)_360px] xl:items-start">
        <div className="flex min-w-0 flex-col gap-3.5">
          <HeroSpotlight
            hero={selected.hero}
            playtime={selected.playtime}
            share={selected.share}
            radar={radarAxes(rows, heroClass)}
            filterSlot={filterSlot}
            metadata={metadata}
          />

          <CardSurface
            title={t("users.heroes.vsAverage")}
            subtitle={lowSampleNote ?? t("users.heroes.vsAverageSubtitle")}
            // On a phone the subtitle goes under the title and the toggle under both, rather than cutting either.
            headerClassName="flex-wrap [&>div:first-child]:flex-wrap [&>div:first-child]:gap-y-0.5"
            action={
              <ToggleGroup
                variant="pill"
                size="sm"
                value={view}
                onValueChange={(value) => setView(value as StatsView)}
                aria-label={t("users.heroes.statsView")}
              >
                <ToggleGroupItem value="overview">{t("users.heroes.overview")}</ToggleGroupItem>
                <ToggleGroupItem value="all">{t("users.heroes.allStats")}</ToggleGroupItem>
              </ToggleGroup>
            }
          >
            {view === "overview" ? (
              <HeroVsAverage rows={overviewRows(rows)} lowSampleNote={lowSampleNote} />
            ) : (
              <HeroStatsTable rows={rows} lowSampleNote={lowSampleNote} />
            )}
          </CardSurface>

          {/* Stretched rows: the records set the height and the maps scroll in it, so both cards end on one line. */}
          <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
            {records.length > 0 ? <HeroBestGames rows={records} /> : null}
            <MapsForHero
              heroName={selected.hero.character.name}
              rows={maps === undefined ? undefined : heroMapRows(maps, heroId)}
              onRetry={retryMaps}
              fill={records.length > 0}
              className={records.length > 0 ? undefined : "lg:col-span-2"}
            />
          </div>
        </div>
        <HeroRail rows={railRows} selectedId={heroId} onSelect={setSelectedId} metadata={metadata} />
      </div>
    </div>
  );
};

export default HeroesView;
