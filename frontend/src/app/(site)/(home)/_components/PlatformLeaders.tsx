import Link from "next/link";
import { useTranslations } from "next-intl";
import { getTranslations } from "next-intl/server";

import type { KpiKey } from "@/components/site/leaders";
import {
  EmptyNote,
  LoadError,
  MoreLink,
  Section,
  SectionHead
} from "@/components/site/open-layout";
import { PlaceBadge } from "@/components/ui/place-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { getFormatter } from "@/lib/datetime/server";
import { getPlayerSlug } from "@/lib/player";
import { cn } from "@/lib/utils";
import statisticsService from "@/services/statistics.service";

import { getPublicWorkspaces } from "./home-data";

const TITLE_ID = "home-leaders-title";
const PRIMARY_KEYS = [
  "tournaments",
  "players",
  "teams",
  "communities"
] as const satisfies readonly KpiKey[];
const SECONDARY_KEYS = [
  "encounters",
  "maps",
  "days",
  "hours",
  "champions"
] as const satisfies readonly KpiKey[];
const METRICS_CLASS = "grid grid-cols-1 gap-x-8 gap-y-6 md:grid-cols-2 xl:grid-cols-4";
const SECONDARY_CLASS = "mt-7 flex flex-wrap gap-x-8 gap-y-3";
const LEADERS_CLASS = "mt-8 grid grid-cols-1 gap-x-10 gap-y-8 md:grid-cols-2";
const PLAYER_LINK_CLASS =
  "grid min-h-11 grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-3 rounded-[var(--aqt-radius-sm)] px-4 text-body text-[color:var(--aqt-fg)] hover:bg-[color:var(--aqt-overlay-1)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[color:var(--aqt-teal)] motion-safe:active:scale-[0.98]";
const WINNER_LINK_CLASS =
  "mb-2 min-h-24 grid-cols-[auto_minmax(0,1fr)] gap-y-3 rounded-[var(--aqt-radius)] border border-[color:var(--aqt-border)] bg-[color:var(--aqt-card)] py-4 sm:grid-cols-[auto_minmax(0,1fr)_auto] sm:px-5";

/** Platform scale first, followed by the two all-time player leaderboards. */
export async function PlatformLeaders() {
  const [t, kpi, format, overall, champions, winrate, workspaces] = await Promise.all([
    getTranslations("home.leaders"),
    getTranslations("site.kpi"),
    getFormatter(),
    statisticsService.getOverallStatistics({ skipWorkspace: true }).catch(() => null),
    statisticsService.getChampions({ skipWorkspace: true }).catch(() => null),
    statisticsService.getTopWinratePlayers({ skipWorkspace: true }).catch(() => null),
    getPublicWorkspaces().catch(() => null)
  ]);

  // Communities come from the public catalogue, not the tournament totals.
  const totals = overall ? { ...overall, communities: workspaces?.length } : null;
  const boards = [
    {
      title: t("mostWins"),
      sub: t("winsSub"),
      rows: champions ? champions.results.slice(0, 5) : null,
      value: "wins"
    },
    {
      title: t("bestWinrate"),
      sub: t("winrateSub"),
      hint: t("winrateTitle"),
      rows: winrate ? winrate.results.slice(0, 5) : null,
      value: "winrate"
    }
  ];

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("totals")}
        titleId={TITLE_ID}
        sub={t("sub")}
        aside={
          <MoreLink href="/statistics" className="min-h-11 whitespace-nowrap">
            {t("more")}
          </MoreLink>
        }
      />
      <div className="border-b border-[color:var(--aqt-border)] pb-7 pt-3">
        {totals === null ? (
          <LoadError />
        ) : (
          <>
            <dl className={METRICS_CLASS}>
              {PRIMARY_KEYS.map((key) => {
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
              {SECONDARY_KEYS.map((key) => {
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
              <p title={board.hint} className="mt-1 text-caption text-[color:var(--aqt-fg-muted)]">
                {board.sub}
              </p>
            </div>
            {board.rows === null ? (
              <LoadError />
            ) : board.rows.length === 0 ? (
              <EmptyNote />
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
    </Section>
  );
}

/** The same metric strip and winner-first lists while the server reads resolve. */
export function PlatformLeadersSkeleton() {
  const t = useTranslations("home.leaders");

  return (
    <Section labelledBy={TITLE_ID}>
      <SectionHead
        title={t("totals")}
        titleId={TITLE_ID}
        sub={t("sub")}
        aside={
          <MoreLink href="/statistics" className="min-h-11 whitespace-nowrap">
            {t("more")}
          </MoreLink>
        }
      />
      <div aria-hidden className="border-b border-[color:var(--aqt-border)] pb-7 pt-3">
        <div className={METRICS_CLASS}>
          {PRIMARY_KEYS.map((key) => (
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
          {SECONDARY_KEYS.map((key) => (
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
    </Section>
  );
}
