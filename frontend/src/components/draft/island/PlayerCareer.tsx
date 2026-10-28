"use client";

import type { UseQueryResult } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import CatalogEntityImage from "@/components/catalog/CatalogEntityImage";
import { useFormatter } from "@/lib/datetime/client";
import PlayerRoleIcon from "@/components/PlayerRoleIcon";
import { Button } from "@/components/ui/button";
import { eyebrowClass } from "@/components/ui/eyebrow";
import { Skeleton } from "@/components/ui/skeleton";
import { RankCrest } from "@/components/RankCrest";
import { roleOf } from "@/lib/roster/role-ref";
import type { RoleOntology } from "@/lib/roster/ontology";
import type { UserDraftCard } from "@/types/user.types";
import type { DivisionGrid } from "@/types/workspace.types";
import { getHeroIconUrl } from "@/lib/player";

/** Below this many maps a winrate is noise: it is hidden, not shown as a verdict. */
export const MIN_WINRATE_MAPS = 10;

export function winrateColor(wonShare: number, maps: number): string {
  if (maps < MIN_WINRATE_MAPS) return "var(--aqt-fg-muted)";
  if (wonShare >= 0.6) return "var(--aqt-positive)";
  if (wonShare >= 0.5) return "var(--aqt-amber)";
  return "var(--aqt-rose-text)";
}

function placeColor(place: number | null): string {
  if (place === 1) return "var(--aqt-medal-gold)";
  if (place === 2) return "var(--aqt-medal-silver)";
  if (place === 3) return "var(--aqt-medal-bronze)";
  return "var(--aqt-fg)";
}

const EYEBROW = eyebrowClass("muted");
const STATS_GRID =
  "grid grid-cols-[repeat(auto-fit,minmax(112px,1fr))] gap-px bg-[color:var(--aqt-border)]";
const STAT_CELL = "flex min-w-0 flex-col gap-0.5 bg-[color:var(--aqt-card-2)] px-3.5 py-2.5";
const STAT_VALUE = "whitespace-nowrap font-onest text-heading font-semibold leading-tight tabular-nums";

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
              <Skeleton variant="text" aria-hidden className="w-16" />
            </div>
            <div className={STAT_VALUE}>
              <Skeleton variant="text" aria-hidden className="w-10" />
            </div>
            <div className="text-xs">
              <Skeleton variant="text" aria-hidden className="w-20" />
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
            ? "var(--aqt-positive)"
            : trend < 0
              ? "var(--aqt-rose-text)"
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
              <span className="whitespace-nowrap rounded border border-[color:var(--aqt-border-2)] px-1.5 text-label font-medium text-[color:var(--aqt-fg-muted)]">
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
 * Top characters and recent tournaments; nothing until the card has history. While
 * the card loads, a stand-in with the rows' own geometry holds their space.
 */
export function CareerTables({
  card,
  pending,
  divisionGrid,
  ontology
}: Readonly<{ card: UserDraftCard | undefined; pending: boolean; divisionGrid: DivisionGrid; ontology: RoleOntology | null }>) {
  const t = useTranslations("draftRedesign");
  const format = useFormatter();

  if (pending) {
    return (
      <div className={TABLES_GRID} aria-hidden>
        <div className={TABLE_SECTION}>
          <div className={`${HERO_GRID} pb-1.5 ${EYEBROW}`}>
            <span />
            <span>
              <Skeleton variant="text" aria-hidden className="w-14" />
            </span>
          </div>
          {SKELETON_ROWS.map((row) => (
            <div key={row} className={`${HERO_GRID} py-1`}>
              <Skeleton className="h-7 w-7 rounded-full" />
              <span className="text-caption">
                <Skeleton variant="text" className="w-20" />
              </span>
            </div>
          ))}
        </div>
        <div className={HISTORY_SECTION}>
          <div className={`${HISTORY_GRID} pb-1.5 ${EYEBROW}`}>
            <span>
              <Skeleton variant="text" className="w-28" />
            </span>
          </div>
          {SKELETON_ROWS.map((row) => (
            <div key={row} className={HISTORY_ROW}>
              <span className="min-w-0">
                <span className="block text-caption">
                  <Skeleton variant="text" className="w-32" />
                </span>
                <span className="block text-xs">
                  <Skeleton variant="text" className="w-16" />
                </span>
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!card || card.tournaments === 0) return null;
  const characters = card.characters ?? [];
  if (characters.length === 0 && card.recent_tournaments.length === 0) return null;

  return (
    <div className={TABLES_GRID}>
      {characters.length > 0 && (
        <section className={TABLE_SECTION} aria-label={t("island.heroes.heading")}>
          <div className={`${HERO_GRID} pb-1.5 ${EYEBROW}`} aria-hidden>
            <span />
            <span>{t("island.heroes.heading")}</span>
            <span className="text-right">{t("island.heroes.maps")}</span>
            <span className="text-right">{t("island.heroes.winrate")}</span>
          </div>
          <ul>
            {characters.slice(0, 5).map((entry) => {
              const share = entry.maps > 0 ? entry.maps_won / entry.maps : 0;
              const low = entry.maps < MIN_WINRATE_MAPS;
              const color = winrateColor(share, entry.maps);
              return (
                <li key={entry.character.id} className={`${HERO_GRID} py-1`}>
                  <CatalogEntityImage
                    entity={{
                      name: entry.character.name,
                      image_path: getHeroIconUrl(entry.character.slug, entry.character.image_path)
                    }}
                    size={28}
                    decorative
                  />
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate text-caption font-medium">{entry.character.name}</span>
                  </span>
                  <span className="text-right text-caption tabular-nums text-[color:var(--aqt-fg-muted)]">
                    {entry.maps}
                  </span>
                  <span
                    className="flex flex-col items-end gap-0.5"
                    title={low ? t("island.stats.winrateHidden") : t("island.heroes.winrateTitle")}
                  >
                    <span className="text-caption font-semibold tabular-nums" style={{ color }}>
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
            {card.recent_tournaments.map((entry) => (
                <li key={entry.id} className={HISTORY_ROW}>
                  <span className="min-w-0">
                    <span className="block truncate text-caption font-medium" title={entry.name}>
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
                    {entry.role && <PlayerRoleIcon role={roleOf(entry.role)} ontology={ontology} size={16} />}
                  </span>
                  <RankCrest
                    rank={entry.rank}
                    grid={divisionGrid}
                    size={20}
                    showValue
                    className="justify-end text-caption text-[color:var(--aqt-fg-muted)]"
                  />
                  <span
                    className="whitespace-nowrap text-right text-caption font-semibold tabular-nums"
                    style={{ color: placeColor(entry.placement) }}
                  >
                    {entry.placement == null ? "—" : `#${entry.placement}`}
                    {entry.teams_count != null && (
                      <span className="font-normal text-[color:var(--aqt-fg-faint)]">{`/${entry.teams_count}`}</span>
                    )}
                  </span>
                </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
