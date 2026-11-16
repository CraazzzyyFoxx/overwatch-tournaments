"use client";

import type { CareerQueue } from "@/types/user.types";
import { useState } from "react";
import { TrendingDown, TrendingUp } from "lucide-react";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Progress } from "@/components/ui/progress";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@craazzzyyfoxx/admin-kit/ui/table";
import { LOW_SAMPLE_GAMES, winrateColor } from "@/lib/colors";
import { useFormatter } from "@/lib/datetime/client";

import { deltaColor, formatStatValue } from "../character/utils";
import { outputRate } from "./career-model";
import { useHeroFaces } from "./use-career";

const LIMIT = 8;
const EMPTY = "—";

const numHeader = "aqt-tnum px-3 py-2.5 text-right";
const numCell = "aqt-tnum px-3 py-2.5 text-right text-caption text-[color:var(--aqt-fg-muted)]";

/**
 * The queue's heroes by time played: share, games, winrate and per-10 rates. With the ladder's meta (PC only, once
 * collected) each row also shows the hero's ladder winrate at the player's division and the player's delta to it.
 */
export default function CareerHeroes({ queue, discipline }: Readonly<{ queue: CareerQueue; discipline: string }>) {
  const t = useTranslations("users.career.heroes");
  const format = useFormatter();
  const faceOf = useHeroFaces(discipline);
  const [expanded, setExpanded] = useState(false);
  const heroes = [...queue.characters].sort((a, b) => b.seconds - a.seconds);
  if (heroes.length === 0) return null;

  const shown = expanded ? heroes : heroes.slice(0, LIMIT);
  const hasMeta = heroes.some((hero) => hero.meta?.winrate != null);
  const percent = (value: number) => format.number(value, { style: "percent", maximumFractionDigits: 0 });

  return (
    <div className="flex flex-col gap-2">
      <Table className="border-collapse">
        <TableHeader>
          <TableRow>
            <TableHead className="px-3 py-2.5">{t("col.hero")}</TableHead>
            <TableHead className="px-3 py-2.5">{t("col.share")}</TableHead>
            <TableHead className={numHeader}>{t("col.games")}</TableHead>
            <TableHead className={numHeader}>{t("col.winrate")}</TableHead>
            <TableHead className={numHeader}>{t("col.eliminations")}</TableHead>
            <TableHead className={numHeader}>{t("col.deaths")}</TableHead>
            <TableHead className={numHeader} title={t("col.outputTitle")}>
              {t("col.output")}
            </TableHead>
            {hasMeta ? (
              <>
                <TableHead className={numHeader} title={t("col.metaTitle")}>
                  {t("col.meta")}
                </TableHead>
                <TableHead className={numHeader} title={t("col.deltaTitle")}>
                  {t("col.delta")}
                </TableHead>
              </>
            ) : null}
          </TableRow>
        </TableHeader>
        <TableBody>
          {shown.map((hero) => {
            const face = faceOf(hero.character);
            const lowSample = (hero.games_played ?? 0) < LOW_SAMPLE_GAMES;
            const output = outputRate(hero.rates, hero.role);
            const metaWinrate = hero.meta?.winrate ?? null;
            const delta = lowSample || hero.winrate == null || metaWinrate == null ? null : hero.winrate - metaWinrate;
            const points = delta == null ? null : Math.round(Math.abs(delta) * 100);
            return (
              <TableRow key={hero.character}>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-2.5">
                    <CatalogEntityImage entity={face} size="sm" decorative />
                    <span className="truncate text-caption font-bold text-[color:var(--aqt-fg)]">{face.name}</span>
                  </div>
                </TableCell>
                <TableCell className="px-3 py-2.5">
                  <div className="flex items-center gap-2">
                    <Progress value={hero.share * 100} size="sm" className="w-16" aria-label={face.name} />
                    <span className="aqt-tnum w-9 text-right text-caption text-[color:var(--aqt-fg-muted)]">
                      {percent(hero.share)}
                    </span>
                  </div>
                </TableCell>
                <TableCell className={numCell}>{hero.games_played ?? EMPTY}</TableCell>
                <TableCell className={numCell}>
                  {hero.winrate == null ? (
                    EMPTY
                  ) : (
                    <span className="font-bold" style={{ color: winrateColor(hero.winrate * 100, lowSample) }}>
                      {percent(hero.winrate)}
                    </span>
                  )}
                </TableCell>
                <TableCell className={numCell}>
                  {hero.rates?.eliminations == null ? EMPTY : formatStatValue(format, "eliminations", hero.rates.eliminations)}
                </TableCell>
                <TableCell className={numCell}>
                  {hero.rates?.deaths == null ? EMPTY : formatStatValue(format, "deaths", hero.rates.deaths)}
                </TableCell>
                <TableCell className={numCell}>
                  {hero.rates?.[output] == null ? EMPTY : formatStatValue(format, "dmg", hero.rates[output])}
                </TableCell>
                {hasMeta ? (
                  <>
                    <TableCell className={numCell}>
                      {metaWinrate == null ? (
                        EMPTY
                      ) : (
                        <span title={t("metaDivision", { division: hero.meta?.division ?? t("allDivisions") })}>
                          {percent(metaWinrate)}
                        </span>
                      )}
                    </TableCell>
                    <TableCell className={numCell}>
                      {delta == null || points == null ? (
                        <span className="text-[color:var(--aqt-fg-faint)]">{EMPTY}</span>
                      ) : (
                        <span className="font-bold" style={{ color: deltaColor(points === 0 ? 0 : delta) }}>
                          {points === 0 ? (
                            <span aria-hidden>–</span>
                          ) : delta > 0 ? (
                            <TrendingUp aria-hidden className="inline size-4 align-[-3px]" />
                          ) : (
                            <TrendingDown aria-hidden className="inline size-4 align-[-3px]" />
                          )}{" "}
                          <span className="sr-only">{points === 0 ? "" : delta > 0 ? "+" : "−"}</span>
                          {t("points", { value: points })}
                        </span>
                      )}
                    </TableCell>
                  </>
                ) : null}
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {heroes.length > LIMIT ? (
        <Button variant="ghost" size="sm" className="self-start" onClick={() => setExpanded((open) => !open)}>
          {expanded ? t("less") : t("more", { count: heroes.length - LIMIT })}
        </Button>
      ) : null}
    </div>
  );
}
