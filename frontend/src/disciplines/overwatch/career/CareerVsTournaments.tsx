"use client";

import type { CareerQueue } from "@/types/user.types";
import { useState } from "react";
import { ArrowDown, ArrowUp } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { CardSurface } from "@/components/profile/atoms";
import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { Button } from "@craazzzyyfoxx/admin-kit/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@craazzzyyfoxx/admin-kit/ui/table";
import { useFormatter } from "@/lib/datetime/client";
import type { StatsScope } from "@/lib/site/stats-scope";
import { userQueryKeys } from "@/lib/users/query-keys";
import userService from "@/services/user.service";

import { formatStatValue } from "../character/utils";
import { compareHero, sharedHeroes, type HeroComparison } from "./career-model";
import { useHeroFaces } from "./use-career";

const LIMIT = 4;
const EMPTY = "—";

/**
 * The heroes the player has on both sides, the ladder's competitive season against our tournaments. Our side is the
 * profile's characters read (the heroes tab's own, so its cache is shared), joined by hero slug. A hero played on one
 * side only is left out. Nothing is drawn while there is nothing to compare, nor when the read fails (the rest of
 * the tab stands on its own).
 */
export default function CareerVsTournaments({
  userId,
  queue,
  discipline,
  scope
}: Readonly<{ userId: number; queue: CareerQueue; discipline: string; scope: StatsScope }>) {
  const t = useTranslations("users.career.vs");
  const tCareer = useTranslations("users.career");
  const format = useFormatter();
  const faceOf = useHeroFaces(discipline);
  const [expanded, setExpanded] = useState(false);
  const ours = useQuery({
    queryKey: userQueryKeys.characters(userId, scope, discipline, undefined),
    queryFn: ({ signal }) => userService.getUserCharacters(userId, discipline, { scope, signal }),
    staleTime: 5 * 60 * 1000
  });
  if (!ours.data) return null;

  const shared = sharedHeroes(queue, ours.data.results);
  if (shared.length === 0) return null;
  const shown = expanded ? shared : shared.slice(0, LIMIT);

  const value = (row: HeroComparison, side: number | null) => {
    if (side == null) return EMPTY;
    return row.rate === "winrate"
      ? format.number(side, { style: "percent", maximumFractionDigits: 0 })
      : formatStatValue(format, row.rate === "deaths" || row.rate === "eliminations" ? row.rate : "dmg", side);
  };

  return (
    <CardSurface title={t("title")} subtitle={queue.season == null ? undefined : tCareer("season", { season: queue.season })} bodyClassName="flex flex-col gap-3">
      <div className="grid grid-cols-1 gap-x-8 gap-y-6 lg:grid-cols-2">
        {shown.map(({ ladder, ours: ourHero }) => {
          const face = faceOf(ladder.character);
          return (
            <section key={ladder.character} aria-label={face.name} className="flex flex-col gap-2">
              <header className="flex items-center gap-2.5">
                <CatalogEntityImage entity={face} size="sm" decorative />
                <span className="text-caption font-bold text-[color:var(--aqt-fg)]">{face.name}</span>
              </header>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="sr-only">{t("stat")}</TableHead>
                    <TableHead className="aqt-tnum w-24 px-0 text-right">{t("ladder")}</TableHead>
                    <TableHead className="aqt-tnum w-28 px-0 text-right">{t("ours")}</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {compareHero(ladder, ourHero).map((row) => (
                    <TableRow key={row.rate}>
                      <TableHead scope="row" className="px-0 py-1.5 font-normal normal-case tracking-normal text-[color:var(--aqt-fg-muted)]">
                        {t(`rate.${row.rate}`)}
                      </TableHead>
                      <TableCell className="aqt-tnum px-0 py-1.5 text-right text-[color:var(--aqt-fg-muted)]">
                        {value(row, row.ladder)}
                      </TableCell>
                      <TableCell className="aqt-tnum px-0 py-1.5 text-right font-semibold text-[color:var(--aqt-fg)]">
                        {value(row, row.ours)}
                        {row.better === null || row.ladder == null || row.ours == null ? null : (
                          <span
                            data-direction={row.ours > row.ladder ? "up" : "down"}
                            className="ml-1.5 inline-flex"
                            style={{ color: row.better ? "var(--aqt-emerald)" : "var(--aqt-rose)" }}
                          >
                            {row.ours > row.ladder ? (
                              <ArrowUp aria-hidden className="size-3.5" />
                            ) : (
                              <ArrowDown aria-hidden className="size-3.5" />
                            )}
                            <span className="sr-only">{row.better ? t("better") : t("worse")}</span>
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="aqt-tnum text-label text-[color:var(--aqt-fg-dim)]">
                {t("footer", { maps: ourHero.games, games: ladder.games_played ?? 0 })}
              </p>
            </section>
          );
        })}
      </div>
      {shared.length > LIMIT ? (
        <Button variant="ghost" size="sm" className="self-start" onClick={() => setExpanded((open) => !open)}>
          {expanded ? t("less") : t("more", { count: shared.length - LIMIT })}
        </Button>
      ) : null}
    </CardSurface>
  );
}
