import type { ReactNode } from "react";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { PlaceBadge } from "@/components/ui/place-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { getPlayerSlug } from "@/lib/player";
import { cn } from "@/lib/utils";
import type { PlayerStatistics } from "@/types/statistics.types";
import { EmptyNote, LoadError } from "./open-layout";

export type KpiKey =
  | "communities"
  | "tournaments"
  | "teams"
  | "players"
  | "encounters"
  | "maps"
  | "days"
  | "hours"
  | "champions";

type MetricKeys = Readonly<{
  primaryKeys: readonly KpiKey[];
  secondaryKeys: readonly KpiKey[];
}>;

const METRICS_CLASS = "grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2 xl:grid-cols-4";
const SECONDARY_CLASS = "mt-7 flex flex-wrap gap-x-8 gap-y-3";
const LEADERS_CLASS = "mt-8 grid grid-cols-1 gap-x-10 gap-y-8 md:grid-cols-2";
const PLAYER_LINK_CLASS =
  "grid min-h-11 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 rounded-[var(--aqt-radius-sm)] px-4 text-body text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-1)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)] motion-safe:active:scale-[0.98]";
const WINNER_LINK_CLASS =
  "mb-2 min-h-24 grid-cols-[auto_minmax(0,1fr)] gap-y-3 rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] py-4 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:px-5";

/** Shared presentation; each caller owns its platform or community data scope. */
export async function LeadersContent({
  totals,
  primaryKeys,
  secondaryKeys,
  boards
}: MetricKeys &
  Readonly<{
    totals: Partial<Record<KpiKey, number | null | undefined>> | null;
    boards: readonly {
      title: ReactNode;
      sub?: ReactNode;
      hint?: string;
      rows: PlayerStatistics[] | null;
      value: "wins" | "winrate";
      empty?: ReactNode;
    }[];
  }>) {
  const [kpi, format] = await Promise.all([getTranslations("site.kpi"), getFormatter()]);

  return (
    <>
      <div className="border-b border-[color:var(--aqt-border)] pb-7 pt-3">
        {totals === null ? (
          <LoadError />
        ) : (
          <>
            <dl className={METRICS_CLASS}>
              {primaryKeys.map((key) => {
                const value = totals[key];
                return typeof value === "number" ? (
                  <div
                    key={key}
                    className="flex items-baseline justify-between gap-4 md:flex-col md:items-start md:gap-2"
                  >
                    <dt className="order-2 text-body text-[color:var(--aqt-fg-muted)]">
                      {kpi(key)}
                    </dt>
                    <dd className="font-display text-display font-semibold tabular-nums text-[color:var(--aqt-fg)]">
                      {format.number(value)}
                    </dd>
                  </div>
                ) : null;
              })}
            </dl>
            <dl className={SECONDARY_CLASS}>
              {secondaryKeys.map((key) => {
                const value = totals[key];
                return typeof value === "number" ? (
                  <div key={key} className="flex items-baseline gap-2">
                    <dt className="text-caption text-[color:var(--aqt-fg-muted)]">{kpi(key)}</dt>
                    <dd className="order-first text-body font-semibold tabular-nums text-[color:var(--aqt-fg)]">
                      {format.number(value)}
                    </dd>
                  </div>
                ) : null;
              })}
            </dl>
          </>
        )}
      </div>
      <div className={LEADERS_CLASS}>
        {boards.map((board) => (
          <div key={board.value} className="min-w-0">
            <div className="mb-4">
              <h3 className="font-display text-heading font-semibold text-[color:var(--aqt-fg)]">
                {board.title}
              </h3>
              {board.sub ? (
                <p
                  title={board.hint}
                  className="mt-1 text-caption text-[color:var(--aqt-fg-muted)]"
                >
                  {board.sub}
                </p>
              ) : null}
            </div>
            {board.rows === null ? (
              <LoadError />
            ) : board.rows.length === 0 ? (
              <EmptyNote>{board.empty}</EmptyNote>
            ) : (
              <ol>
                {board.rows.map((player, index) => (
                  <li key={player.id}>
                    <Link
                      href={`/users/${getPlayerSlug(player.name)}`}
                      prefetch={false}
                      title={player.name}
                      className={cn(PLAYER_LINK_CLASS, index === 0 && WINNER_LINK_CLASS)}
                    >
                      {index === 0 ? (
                        <PlaceBadge place={1} className="size-8 min-w-8 px-0" />
                      ) : (
                        <span className="inline-flex size-8 items-center justify-center text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
                          {index + 1}
                        </span>
                      )}
                      <span
                        className={cn(
                          "min-w-0 truncate font-semibold",
                          index === 0 && "font-display text-heading"
                        )}
                      >
                        {player.name}
                      </span>
                      <span
                        className={cn(
                          "whitespace-nowrap text-right font-semibold tabular-nums text-[color:var(--aqt-teal)]",
                          index === 0 &&
                            "col-start-2 text-left font-display text-headline sm:col-start-3 sm:row-start-1 sm:text-right"
                        )}
                      >
                        {board.value === "wins"
                          ? `${format.number(player.value)}×`
                          : format.number(player.value, {
                              style: "percent",
                              minimumFractionDigits: 1,
                              maximumFractionDigits: 1
                            })}
                      </span>
                    </Link>
                  </li>
                ))}
              </ol>
            )}
          </div>
        ))}
      </div>
    </>
  );
}

/** Matches the headline totals and winner-first lists on both public pages. */
export function LeadersSkeleton({ primaryKeys, secondaryKeys }: MetricKeys) {
  return (
    <>
      <div aria-hidden className="border-b border-[color:var(--aqt-border)] pb-7 pt-3">
        <div className={METRICS_CLASS}>
          {primaryKeys.map((key) => (
            <div
              key={key}
              className="flex items-baseline justify-between gap-4 md:flex-col md:items-start md:gap-2"
            >
              <Skeleton className="h-8 w-28 md:h-14" />
              <Skeleton className="h-5 w-24" />
            </div>
          ))}
        </div>
        <div className={SECONDARY_CLASS}>
          {secondaryKeys.map((key) => (
            <Skeleton key={key} className="h-5 w-24" />
          ))}
        </div>
      </div>
      <div aria-hidden className={LEADERS_CLASS}>
        {["wins", "winrate"].map((board) => (
          <div key={board} className="min-w-0">
            <div className="mb-4">
              <Skeleton className="h-6 w-44" />
              <Skeleton className="mt-1 h-5 w-32" />
            </div>
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className={cn(PLAYER_LINK_CLASS, index === 0 && WINNER_LINK_CLASS)}>
                <Skeleton className="size-8" />
                <Skeleton className="h-5 w-full max-w-44" />
                <Skeleton
                  className={cn(
                    "h-5 w-14",
                    index === 0 && "col-start-2 h-8 w-20 sm:col-start-3 sm:row-start-1"
                  )}
                />
              </div>
            ))}
          </div>
        ))}
      </div>
    </>
  );
}
