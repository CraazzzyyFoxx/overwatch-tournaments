"use client";

import { useTranslations } from "next-intl";

import { HandleLabel } from "@/components/HandleLabel";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

import { shareOfBest, type RankedEntry } from "./board";
import RankBadge from "./RankBadge";
import type { StatColumnDef } from "./stat-columns";

const TOP = 10;

/**
 * The board's answer at a glance: the ten best players by the stat ordering the board, each bar the value as a share
 * of the leader's. It follows "Rank by", so the chart and the table always rank the same way.
 */
export default function TopChart({
  def,
  ranked,
  minGames,
  isLoading
}: Readonly<{ def: StatColumnDef; ranked: readonly RankedEntry[]; minGames: number; isLoading: boolean }>) {
  const t = useTranslations();
  const top = ranked.slice(0, TOP);
  const best = top[0] ? def.getValue(top[0].entry) : 0;

  return (
    <Card asChild><section className="flex flex-col p-5">
      <header className="mb-3 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="font-onest text-lg font-semibold text-[color:var(--aqt-fg)]">
          {t("users.heroesCompare.top.title", { stat: t(def.labelKey) })}
        </h3>
        {minGames > 1 ? (
          <span className="text-label text-[color:var(--aqt-fg-faint)] md:ml-auto">
            {t("users.heroesCompare.top.floor", { min: minGames })}
          </span>
        ) : null}
      </header>
      {isLoading ? (
        <div className="grid gap-2">
          {Array.from({ length: TOP }).map((_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </div>
      ) : top.length === 0 ? (
        <p className="py-10 text-center text-caption text-[color:var(--aqt-fg-dim)]">{t("users.heroesCompare.table.noData")}</p>
      ) : (
        <ol className="grid gap-1">
          {top.map(({ entry, rank }, i) => {
            const value = def.getValue(entry);
            return (
              <li
                key={entry.user_id}
                className="grid grid-cols-[26px_minmax(0,1fr)_64px] items-center gap-x-3 gap-y-1 py-1 text-caption md:grid-cols-[26px_minmax(0,11rem)_minmax(0,1fr)_64px_72px]"
              >
                <RankBadge rank={rank} />
                <HandleLabel
                  handle={entry.username}
                  title={entry.username}
                  className="font-semibold text-[color:var(--aqt-fg)]"
                />
                <span
                  aria-hidden
                  className="relative col-span-2 col-start-2 row-start-2 h-1.5 rounded-full md:col-span-1 md:col-start-auto md:row-start-auto md:h-3.5"
                >
                  <span
                    className={cn(
                      "absolute inset-y-0 left-0 rounded-full md:rounded-[4px]",
                      i === 0
                        ? "bg-[color:var(--aqt-teal)]"
                        : "bg-[color:color-mix(in_srgb,var(--aqt-teal)_34%,transparent)]"
                    )}
                    style={{ width: `${shareOfBest(best, value, def.ascending) * 100}%` }}
                  />
                </span>
                <span className="text-right font-bold tabular-nums text-[color:var(--aqt-fg)]">{def.formatValue(value)}</span>
                <span className="text-right text-label tabular-nums text-[color:var(--aqt-fg-faint)] max-md:hidden">
                  {t("users.heroesCompare.top.games", { count: entry.games_played })}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section></Card>
  );
}
