"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import DivisionIcon from "@/components/DivisionIcon";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { getDivisionLabel, resolveDivisionFromRank } from "@/lib/divisions/grid";
import { getRoleIconName } from "@/lib/roster/roles";
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
 * The career row under the card header. Owns the card query's loading and
 * error states; the tables below only render once there is history.
 */
export function CareerStats({ query }: Readonly<{ query: UseQueryResult<UserDraftCard> }>) {
  const t = useTranslations("draftRedesign");

  if (query.isPending) {
    return (
      <div className="grid grid-cols-2 gap-px border-b border-[color:var(--aqt-border)] sm:grid-cols-5" aria-busy>
        <span className="sr-only">{t("profile.stats.loading")}</span>
        {[0, 1, 2, 3, 4].map((cell) => (
          <div key={cell} className="px-3.5 py-2.5">
            <div className="h-3 w-16 animate-pulse rounded bg-[color:var(--aqt-overlay-3)] motion-reduce:animate-none" />
            <div className="mt-2 h-5 w-12 animate-pulse rounded bg-[color:var(--aqt-overlay-3)] motion-reduce:animate-none" />
          </div>
        ))}
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="flex items-center gap-3 border-b border-[color:var(--aqt-border)] px-3.5 py-3 text-sm text-[color:var(--aqt-fg-muted)]">
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
      <p className="border-b border-[color:var(--aqt-border)] px-3.5 py-3 text-sm text-[color:var(--aqt-fg-muted)]">
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
    <dl className="grid grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-px border-b border-[color:var(--aqt-border)] bg-[color:var(--aqt-border)]">
      {stats.map((stat) => (
        <div
          key={stat.key}
          title={stat.title}
          className="flex min-w-0 flex-col gap-0.5 bg-[color:var(--aqt-card-2)] px-3.5 py-2.5"
        >
          <dt className={`truncate ${EYEBROW}`}>{stat.label}</dt>
          <dd className="flex min-w-0 items-center gap-1.5">
            <span
              className="whitespace-nowrap font-onest text-[19px] font-semibold leading-tight tabular-nums"
              style={{ color: stat.color }}
            >
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

/** Top heroes and recent tournaments; nothing until the card has history. */
export function CareerTables({
  card,
  divisionGrid
}: Readonly<{ card: UserDraftCard | undefined; divisionGrid: DivisionGrid }>) {
  const t = useTranslations("draftRedesign");
  const locale = useLocale();

  if (!card || card.tournaments === 0) return null;
  if (card.heroes.length === 0 && card.recent_tournaments.length === 0) return null;
  const dateFormat = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short", year: "numeric" });

  return (
    <div className="grid grid-cols-[repeat(auto-fit,minmax(290px,1fr))] border-t border-[color:var(--aqt-border)]">
      {card.heroes.length > 0 && (
        <section className="min-w-0 pb-2 pt-2.5" aria-label={t("island.heroes.heading")}>
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
        <section
          className="min-w-0 border-[color:var(--aqt-border)] pb-2 pt-2.5 [&:not(:first-child)]:border-l"
          aria-label={t("island.recent.heading")}
        >
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
                <li key={entry.id} className={`${HISTORY_GRID} min-h-[30px] py-1`}>
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium" title={entry.name}>
                      {entry.name}
                    </span>
                    {entry.date && (
                      <span className="block whitespace-nowrap text-xs text-[color:var(--aqt-fg-faint)]">
                        {dateFormat.format(new Date(entry.date))}
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
