"use client";

import { useTranslations } from "next-intl";
import { useFormatter } from "@/lib/datetime/client";
import { ArrowRight, TrendingDown, TrendingUp } from "lucide-react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import type { SlotProps } from "@/disciplines/types";
import { LogStatsName } from "../stat-names";
import { characterClass } from "@/lib/catalog/attrs";
import { CARD_HEAD_LINK, CardSurface } from "@/components/profile/atoms";
import { formatSeconds } from "@/lib/format";
import { formatStatValue, getOverall, heroWinrate, statAvg10 } from "./utils";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Eyebrow } from "@/components/ui/eyebrow";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { HeroStatsPopover } from "./HeroUserStatsPopover";
import { useHeroClass } from "./classes";

const LIMIT = 8;

interface Row {
  id: number;
  hero: SlotProps["topCharacters"]["characters"][number];
  heroClass: string | undefined;
  games: number;
  /** Total seconds on the hero — this is what the table is ordered by. */
  playtime: number;
  /** Share of the player's total playtime across all heroes (0..1). */
  share: number | null;
  winPct: number | null;
  kda: number | null;
  dmg10: number | null;
  /** Player winrate minus the global average on this hero (fraction). */
  vsAvg: number | null;
  lowSample: boolean;
}

/** Placeholder for a cell with no value. One glyph everywhere: the table used to
 *  mix an em dash (winrate) with an en dash (vs-avg) in the same row. */
const EMPTY = "—";

const numHeader = "aqt-tnum px-3 py-2.5 text-right";
const numCell = "aqt-tnum px-3 py-2.5 text-right text-caption text-[color:var(--aqt-fg-muted)]";

/** Overwatch's most-played heroes on the profile overview (the `topCharacters` slot). */
const TopHeroesTable = ({ characters, userSlug, metadata }: SlotProps["topCharacters"]) => {
  const t = useTranslations();
  const format = useFormatter();
  const heroClass = useHeroClass(metadata);
  if (characters.length === 0) return null;

  const withPlaytime = characters.map((h) => ({ h, playtime: getOverall(h, LogStatsName.HeroTimePlayed) }));
  const totalPlaytime = withPlaytime.reduce((sum, x) => sum + x.playtime, 0);

  const rows: Row[] = withPlaytime
    .sort((a, b) => b.playtime - a.playtime)
    .slice(0, LIMIT)
    .map(({ h, playtime }) => {
      const winFrac = heroWinrate(h);
      const lowSample = h.games < LOW_SAMPLE_GAMES;
      return {
        id: h.character.id,
        hero: h,
        heroClass: characterClass(h.character),
        games: h.games,
        playtime,
        share: totalPlaytime > 0 ? playtime / totalPlaytime : null,
        winPct: lowSample || winFrac == null ? null : winFrac * 100,
        kda: statAvg10(h.stats, LogStatsName.KDA),
        dmg10: statAvg10(h.stats, LogStatsName.HeroDamageDealt),
        vsAvg: lowSample || winFrac == null || h.win_rate_all == null ? null : winFrac - h.win_rate_all,
        lowSample
      };
    });

  // Only render a metric column when at least one row can fill it: a player without scored games (no parsed logs)
  // would otherwise get full columns of dashes.
  const columns = {
    games: rows.some((r) => r.games > 0),
    playtime: rows.some((r) => r.playtime > 0),
    share: totalPlaytime > 0,
    winrate: rows.some((r) => r.winPct != null),
    kda: rows.some((r) => r.kda != null),
    dmg10: rows.some((r) => r.dmg10 != null),
    vsAvg: rows.some((r) => r.vsAvg != null)
  };

  const lowSampleTitle = t("users.overview.topHeroes.lowSampleTitle", { games: LOW_SAMPLE_GAMES });

  return (
    <CardSurface
      title={t("users.overview.topHeroes.title")}
      subtitle={t("users.overview.topHeroes.playedByTime", { count: characters.length })}
      action={
        <HoverPrefetchLink href={`/users/${userSlug}?tab=heroes`} className={CARD_HEAD_LINK}>
          {t("common.all")} {characters.length}
          <ArrowRight aria-hidden className="size-3" />
        </HoverPrefetchLink>
      }
    >
      <Table className="border-collapse">
        <TableHeader>
          <TableRow>
            <TableHead className="aqt-tnum px-3 py-2.5">{t("users.overview.topHeroes.col.hero")}</TableHead>
            <TableHead className="aqt-tnum px-3 py-2.5 text-center">{t("users.overview.topHeroes.col.role")}</TableHead>
            {columns.games ? <TableHead className={numHeader}>{t("users.overview.topHeroes.col.games")}</TableHead> : null}
            {columns.playtime ? <TableHead className={numHeader}>{t("users.overview.topHeroes.col.time")}</TableHead> : null}
            {columns.share ? (
              <TableHead className={numHeader} title={t("users.overview.topHeroes.col.shareTitle")}>
                {t("users.overview.topHeroes.col.share")}
              </TableHead>
            ) : null}
            {columns.winrate ? <TableHead className={numHeader}>{t("users.overview.topHeroes.col.winrate")}</TableHead> : null}
            {columns.kda ? <TableHead className={numHeader}>{t("users.overview.topHeroes.col.kda")}</TableHead> : null}
            {columns.dmg10 ? <TableHead className={numHeader}>{t("users.overview.topHeroes.col.dmg10")}</TableHead> : null}
            {columns.vsAvg ? <TableHead className={numHeader}>{t("users.overview.topHeroes.col.vsAvg")}</TableHead> : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((r) => {
            const roleName = heroClass.label(r.heroClass);
            return (
              <TableRow key={r.id}>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-2.5">
                    <CatalogEntityImage
                      entity={r.hero.character}
                      size="sm"
                      title={r.hero.character.name}
                      popover={<HeroStatsPopover hero={r.hero} metadata={metadata} />}
                    />
                    <div className="min-w-0">
                      <div className="truncate text-caption font-bold text-[color:var(--aqt-fg)]">
                        {r.hero.character.name}
                      </div>
                      {r.lowSample ? (
                        <Eyebrow className="aqt-tnum" title={lowSampleTitle}>
                          {t("users.overview.topHeroes.lowSample")}
                        </Eyebrow>
                      ) : null}
                    </div>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex justify-center" title={roleName}>
                    {heroClass.icon(r.heroClass, 16)}
                    <span className="sr-only">{roleName}</span>
                  </div>
                </TableCell>
                {columns.games ? <TableCell className={numCell}>{r.games}</TableCell> : null}
                {columns.playtime ? (
                  <TableCell className={numCell}>{r.playtime > 0 ? formatSeconds(r.playtime) : EMPTY}</TableCell>
                ) : null}
                {columns.share ? (
                  <TableCell className={numCell}>{r.share == null ? EMPTY : `${(r.share * 100).toFixed(0)}%`}</TableCell>
                ) : null}
                {columns.winrate ? (
                  <TableCell className={numCell}>
                    {r.winPct == null ? (
                      <span title={r.lowSample ? lowSampleTitle : undefined} className="text-[color:var(--aqt-fg-faint)]">
                        {EMPTY}
                      </span>
                    ) : (
                      <span className="font-bold" style={{ color: winrateColor(r.winPct) }}>
                        {r.winPct.toFixed(0)}%
                      </span>
                    )}
                  </TableCell>
                ) : null}
                {columns.kda ? (
                  <TableCell className={`${numCell} font-semibold text-[color:var(--aqt-fg)]`}>
                    {r.kda == null ? EMPTY : r.kda.toFixed(2)}
                  </TableCell>
                ) : null}
                {columns.dmg10 ? (
                  <TableCell className={numCell}>{r.dmg10 == null ? EMPTY : formatStatValue(format, "dmg", r.dmg10)}</TableCell>
                ) : null}
                {columns.vsAvg ? (
                  <TableCell className={numCell}>
                    {r.vsAvg == null ? (
                      <span
                        className="text-[color:var(--aqt-fg-faint)]"
                        title={r.lowSample ? lowSampleTitle : t("users.overview.topHeroes.vsAvgTitle")}
                      >
                        {EMPTY}
                      </span>
                    ) : (
                      <span
                        className="font-bold"
                        title={t("users.overview.topHeroes.vsAvgTitle")}
                        style={{
                          color:
                            r.vsAvg > 0
                              ? "var(--aqt-emerald)"
                              : r.vsAvg < 0
                                ? "var(--aqt-rose)"
                                : "var(--aqt-fg-muted)"
                        }}
                      >
                        {r.vsAvg > 0 ? (
                          <TrendingUp aria-hidden className="inline size-4 align-[-3px]" />
                        ) : r.vsAvg < 0 ? (
                          <TrendingDown aria-hidden className="inline size-4 align-[-3px]" />
                        ) : (
                          <span aria-hidden>–</span>
                        )}{" "}
                        {/* The icon is decorative; direction reaches AT through this. */}
                        <span className="sr-only">{r.vsAvg > 0 ? "+" : r.vsAvg < 0 ? "−" : ""}</span>
                        {Math.abs(r.vsAvg * 100).toFixed(0)}
                      </span>
                    )}
                  </TableCell>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </CardSurface>
  );
};

export default TopHeroesTable;
