"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import { useFormatter } from "@/lib/datetime/client";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { getRoleIconName } from "@/lib/roster/roles";
import { cn } from "@/lib/utils";
import type { UserDraftCard } from "@/types/user.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { getHeroIconUrl } from "@/utils/player";

/** Below this many maps a winrate is noise: it is hidden, not shown as a verdict. */
export const MIN_WINRATE_MAPS = 10;

export function winrateColor(wonShare: number, maps: number): string {
  if (maps < MIN_WINRATE_MAPS) return "var(--aqt-fg-muted)";
  if (wonShare >= 0.6) return "var(--aqt-support)";
  if (wonShare >= 0.5) return "var(--aqt-amber)";
  return "var(--aqt-rose)";
}

export function placeColor(place: number | null): string {
  if (place === 1) return "var(--aqt-medal-gold)";
  if (place === 2) return "var(--aqt-medal-silver)";
  if (place === 3) return "var(--aqt-medal-bronze)";
  return "var(--aqt-fg)";
}

const EYEBROW = "text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-faint)]";
const STATS_GRID =
  "grid grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-px bg-[color:var(--aqt-border)]";
const STAT_CELL = "flex min-w-0 flex-col gap-0.5 bg-[color:var(--aqt-card-2)] px-3.5 py-2.5";
const STAT_VALUE = "whitespace-nowrap font-onest text-[19px] font-semibold leading-tight tabular-nums";

/**
 * A loading stand-in for one line of text. It sits in the line box of a parent
 * carrying the real text's classes, so the value that replaces it takes exactly
 * the same height and the card does not shift when the data lands. Never make
 * it a grid or flex item itself: that blockifies it to its own 0.8em height.
 */
export function Bar({ className }: Readonly<{ className: string }>) {
  return (
    <span
      aria-hidden
      className={cn(
        "inline-block h-[0.8em] animate-pulse rounded bg-[color:var(--aqt-overlay-3)] align-middle motion-reduce:animate-none",
        className
      )}
    />
  );
}

interface Stat {
  key: string;
  label: string;
  value: string;
  sub: string;
  color: string;
  title: string;
  low?: boolean;
}

/**
 * The career row at the top of the Statistics view. Owns the card query's
 * loading and error states; the tables below only render once there is history.
 */
export function CareerStats({ query }: Readonly<{ query: UseQueryResult<UserDraftCard> }>) {
  const t = useTranslations("draftRedesign");

  if (query.isPending) {
    return (
      <div className={STATS_GRID} aria-busy>
        <span className="sr-only">{t("profile.stats.loading")}</span>
        {[0, 1, 2, 3, 4].map((cell) => (
          <div key={cell} className={STAT_CELL}>
            <div className={EYEBROW}>
              <Bar className="w-16" />
            </div>
            <div className={STAT_VALUE}>
              <Bar className="w-10" />
            </div>
            <div className="text-xs">
              <Bar className="w-20" />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="flex items-center gap-3 px-3.5 py-3 text-sm text-[color:var(--aqt-fg-muted)]">
        <p className="min-w-0 flex-1">{t("profile.stats.error")}</p>
        <Button variant="outline" size="sm" onClick={() => query.refetch()}>
          {t("profile.stats.retry")}
        </Button>
      </div>
    );
  }

  const card = query.data;
  if (card.tournaments === 0) {
    return (
      <p className="px-3.5 py-3 text-sm text-[color:var(--aqt-fg-muted)]">
        {t("island.firstTournament")}
      </p>
    );
  }

  const lowMaps = card.maps < MIN_WINRATE_MAPS;
  const share = card.maps > 0 ? card.maps_won / card.maps : 0;
  // Newest first: the trend is the latest ranked tournament against the oldest shown.
  const ranks = card.recent_tournaments.flatMap((entry) => (entry.rank == null ? [] : [entry.rank]));
  const trend = ranks.length > 1 ? ranks[0] - ranks[ranks.length - 1] : null;

  const stats: Stat[] = [
    {
      key: "tournaments",
      label: t("island.stats.tournaments"),
      value: String(card.tournaments),
      sub: t("island.stats.wins", { n: card.tournaments_won }),
      color: "var(--aqt-fg)",
      title: t("island.stats.tournamentsTitle")
    },
    {
      key: "maps",
      label: t("island.stats.maps"),
      value: String(card.maps),
      sub: card.mvp_maps == null ? "—" : t("island.stats.mvp", { n: card.mvp_maps }),
      color: "var(--aqt-fg)",
      title: t("island.stats.mapsTitle")
    },
    {
      key: "winrate",
      label: t("island.stats.winrate"),
      value: lowMaps ? "—" : `${Math.round(share * 100)}%`,
      sub: lowMaps ? t("island.stats.winrateLow") : `${card.maps_won}–${card.maps_lost}`,
      color: winrateColor(share, card.maps),
      title: lowMaps ? t("island.stats.winrateHidden") : t("island.stats.winrateTitle"),
      low: lowMaps
    },
    {
      key: "place",
      label: t("island.stats.best"),
      value: card.best_placement == null ? "—" : `#${card.best_placement}`,
      sub: card.avg_placement == null ? "—" : t("island.stats.avg", { place: Math.round(card.avg_placement) }),
      color: card.best_placement == null ? "var(--aqt-fg-muted)" : placeColor(card.best_placement),
      title: t("island.stats.bestTitle")
    },
    {
      key: "trend",
      label: t("island.stats.trend"),
      value: trend == null ? "—" : `${trend > 0 ? "+" : trend < 0 ? "−" : ""}${Math.abs(trend)}`,
      sub: ranks.length > 1 ? t("island.stats.trendOver", { n: ranks.length }) : t("island.stats.trendSingle"),
      color:
        trend == null
          ? "var(--aqt-fg-muted)"
          : trend > 0
            ? "var(--aqt-support)"
            : trend < 0
              ? "var(--aqt-rose)"
              : "var(--aqt-fg)",
      title: t("island.stats.trendTitle")
    }
  ];

  return (
    <dl className={STATS_GRID}>
      {stats.map((stat) => (
        <div key={stat.key} title={stat.title} className={STAT_CELL}>
          <dt className={`truncate ${EYEBROW}`}>{stat.label}</dt>
          <dd className="flex min-w-0 items-center gap-1.5">
            <span className={STAT_VALUE} style={{ color: stat.color }}>
              {stat.value}
            </span>
            {stat.low && (
              <span className="whitespace-nowrap rounded border border-[color:var(--aqt-border-2)] px-1.5 text-label font-medium uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
                {t("island.stats.lowSample")}
              </span>
            )}
          </dd>
          <dd className="truncate text-xs tabular-nums text-[color:var(--aqt-fg-muted)]">{stat.sub}</dd>
        </div>
      ))}
    </dl>
  );
}

const HERO_GRID = "grid grid-cols-[28px_minmax(0,1fr)_48px_92px] items-center gap-2.5 px-3.5";
const HISTORY_GRID = "grid grid-cols-[minmax(0,1fr)_18px_84px_56px] items-center gap-2.5 px-3.5";
const TABLES_GRID = "grid grid-cols-[repeat(auto-fit,minmax(290px,1fr))] border-t border-[color:var(--aqt-border)]";
const TABLE_SECTION = "min-w-0 pb-2 pt-2.5";
const HISTORY_SECTION = `${TABLE_SECTION} border-[color:var(--aqt-border)] [&:not(:first-child)]:border-l`;
const HISTORY_ROW = `${HISTORY_GRID} min-h-[30px] py-1`;
/** Both lists are cut at five, and five is what a returning player has. */
const SKELETON_ROWS = [0, 1, 2, 3, 4];

/**
 * Top heroes and recent tournaments; nothing until the card has history. While
 * the card loads, a stand-in with the rows' own geometry holds their space.
 */
export function CareerTables({
  card,
  pending,
  divisionGrid
}: Readonly<{ card: UserDraftCard | undefined; pending: boolean; divisionGrid: DivisionGrid }>) {
  const t = useTranslations("draftRedesign");
  const format = useFormatter();

  if (pending) {
    return (
      <div className={TABLES_GRID} aria-hidden>
        <div className={TABLE_SECTION}>
          <div className={`${HERO_GRID} pb-1.5 ${EYEBROW}`}>
            <span />
            <span>
              <Bar className="w-14" />
            </span>
          </div>
          {SKELETON_ROWS.map((row) => (
            <div key={row} className={`${HERO_GRID} py-1`}>
              <span className="h-7 w-7 animate-pulse rounded-full bg-[color:var(--aqt-overlay-3)] motion-reduce:animate-none" />
              <span className="text-[13px]">
                <Bar className="w-20" />
              </span>
            </div>
          ))}
        </div>
        <div className={HISTORY_SECTION}>
          <div className={`${HISTORY_GRID} pb-1.5 ${EYEBROW}`}>
            <span>
              <Bar className="w-28" />
            </span>
          </div>
          {SKELETON_ROWS.map((row) => (
            <div key={row} className={HISTORY_ROW}>
              <span className="min-w-0">
                <span className="block text-[13px]">
                  <Bar className="w-32" />
                </span>
                <span className="block text-xs">
                  <Bar className="w-16" />
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!card || card.tournaments === 0) return null;
  if (card.heroes.length === 0 && card.recent_tournaments.length === 0) return null;

  return (
    <div className={TABLES_GRID}>
      {card.heroes.length > 0 && (
        <section className={TABLE_SECTION} aria-label={t("island.heroes.heading")}>
          <div className={`${HERO_GRID} pb-1.5 ${EYEBROW}`} aria-hidden>
            <span />
            <span>{t("island.heroes.heading")}</span>
            <span className="text-right">{t("island.heroes.maps")}</span>
            <span className="text-right">{t("island.heroes.winrate")}</span>
          </div>
          <ul>
            {card.heroes.slice(0, 5).map((entry) => {
              const share = entry.maps > 0 ? entry.maps_won / entry.maps : 0;
              const low = entry.maps < MIN_WINRATE_MAPS;
              const color = winrateColor(share, entry.maps);
              return (
                <li key={`${entry.hero.id}-${entry.role}`} className={`${HERO_GRID} py-1`}>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={getHeroIconUrl(entry.hero.slug, entry.hero.image_path)}
                    alt=""
                    width={28}
                    height={28}
                    className="h-7 w-7 rounded-full object-cover"
                  />
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-[13px] font-medium">{entry.hero.name}</span>
                    <PlayerRoleIcon role={getRoleIconName(entry.role)} size={14} />
                  </span>
                  <span className="text-right text-[13px] tabular-nums text-[color:var(--aqt-fg-muted)]">
                    {entry.maps}
                  </span>
                  <span
                    className="flex flex-col items-end gap-0.5"
                    title={low ? t("island.stats.winrateHidden") : t("island.heroes.winrateTitle")}
                  >
                    <span className="text-[13px] font-semibold tabular-nums" style={{ color }}>
                      {low ? "—" : `${Math.round(share * 100)}%`}
                    </span>
                    <span className="h-[3px] w-full overflow-hidden rounded-sm bg-[color:var(--aqt-overlay-3)]" aria-hidden>
                      <span
                        className="block h-full"
                        style={{ width: low ? "0%" : `${Math.round(share * 100)}%`, background: color }}
                      />
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {card.recent_tournaments.length > 0 && (
        <section className={HISTORY_SECTION} aria-label={t("island.recent.heading")}>
          <div className={`${HISTORY_GRID} pb-1.5 ${EYEBROW}`} aria-hidden>
            <span>{t("island.recent.heading")}</span>
            <span />
            <span className="text-right">{t("island.recent.rank")}</span>
            <span className="text-right">{t("island.recent.place")}</span>
          </div>
          <ul>
            {card.recent_tournaments.map((entry) => {
              const division = resolveDivisionFromRank(divisionGrid, entry.rank);
              const crestLabel = division != null ? getDivisionLabel(divisionGrid, division) : null;
              return (
                <li key={entry.id} className={HISTORY_ROW}>
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium" title={entry.name}>
                      {entry.name}
                    </span>
                    {entry.date && (
                      <span className="block whitespace-nowrap text-xs text-[color:var(--aqt-fg-faint)]">
                        {/* A tournament's start day, stored as a UTC midnight. */}
                        {format.dateTime(new Date(entry.date), { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" })}
                      </span>
                    )}
                  </span>
                  <span className="flex justify-center">
                    {entry.role && <PlayerRoleIcon role={getRoleIconName(entry.role)} size={16} />}
                  </span>
                  <span className="flex items-center justify-end gap-1.5" title={crestLabel ?? undefined}>
                    {division != null && (
                      <DivisionIcon
                        division={division}
                        tournamentGrid={divisionGrid}
                        width={20}
                        height={20}
                        className="h-5 w-5 shrink-0 object-contain"
                      />
                    )}
                    <span className="text-[13px] tabular-nums text-[color:var(--aqt-fg-muted)]">
                      {entry.rank ?? "—"}
                    </span>
                  </span>
                  <span
                    className="whitespace-nowrap text-right text-[13px] font-semibold tabular-nums"
                    style={{ color: placeColor(entry.placement) }}
                  >
                    {entry.placement == null ? "—" : `#${entry.placement}`}
                    {entry.teams_count != null && (
                      <span className="font-normal text-[color:var(--aqt-fg-faint)]">{`/${entry.teams_count}`}</span>
                    )}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}
    </div>
  );
}
