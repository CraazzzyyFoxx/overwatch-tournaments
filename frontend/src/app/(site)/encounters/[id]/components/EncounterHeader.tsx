import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import { TeamLogo } from "@/components/TeamName";
import { acceptedScore } from "@/components/pick-ban/pick-ban-model";
import {
  buildSeriesSlots,
  getSeriesVerdict,
  type SeriesSide,
  type SeriesSlot
} from "@/lib/encounter/detail";
import styles from "@/components/match/EncounterDetail.module.css";

export type EncounterHeaderFact = { label: string; value: string; sub?: string };

/**
 * The match, stated once: where it sits, who played, the result, and the few
 * facts about the series. The hero and the scoreboard under it used to say the
 * same thing three times — "A vs B" as a title, "A took the series 3–2" as a
 * lede, then the 3:2 board — before the page reached any content.
 */
export default function EncounterHeader({
  encounter,
  crumbs,
  actions,
  pills,
  facts
}: Readonly<{
  encounter: Encounter;
  crumbs: ReactNode;
  actions: ReactNode;
  /** Chips for states that want attention; nothing is rendered without one. */
  pills?: ReactNode;
  facts: EncounterHeaderFact[];
}>) {
  const t = useTranslations();
  const slots = buildSeriesSlots(encounter);
  const verdict = getSeriesVerdict(encounter);
  const homeName = encounter.home_team?.name ?? t("common.tbd");
  const awayName = encounter.away_team?.name ?? t("common.tbd");

  return (
    <header className={cn(styles.card, styles.header)}>
      <div className={styles.headerTop}>
        <div className={styles.headerCrumbs}>{crumbs}</div>
        <div className={styles.heroActions}>{actions}</div>
      </div>

      {/* The page's one h1: the matchup, read by the outline the way the old
          hero title was, while the board below draws it. */}
      <h1 className="sr-only">{t("encounters.detail.heroTitle", { home: homeName, away: awayName })}</h1>
      <div className={styles.board}>
        <TeamBlock encounter={encounter} side="home" />
        <div className={styles.boardCenter}>
          <p className={styles.boardScore}>
            <span className={styles.scoreHome}>{encounter.score.home}</span>
            <span aria-hidden className={styles.scoreSep}>
              :
            </span>
            <span className={styles.scoreAway}>{encounter.score.away}</span>
          </p>
          <p className={styles.boardVerdict}>
            {verdict.outcome === "win"
              ? t("encounters.detail.verdictWin", {
                  team: verdict.winner === "home" ? homeName : awayName
                })
              : verdict.outcome === "draw"
                ? t("encounters.detail.verdictDraw")
                : t("encounters.detail.verdictPending")}
          </p>
          <MapPips slots={slots} />
        </div>
        <TeamBlock encounter={encounter} side="away" />
      </div>

      <div className={styles.headerFoot}>
        {pills ? <div className={styles.boardTags}>{pills}</div> : null}
        {facts.length > 0 ? (
          <dl className={styles.headerFacts}>
            {facts.map((fact) => (
              <div key={fact.label} className={styles.headerFact}>
                <dt className={styles.label}>{fact.label}</dt>
                <dd className={styles.headerFactValue}>
                  {fact.value}
                  {fact.sub ? <span className={styles.headerFactSub}>{fact.sub}</span> : null}
                </dd>
              </div>
            ))}
          </dl>
        ) : null}
      </div>
    </header>
  );
}

function TeamBlock({ encounter, side }: Readonly<{ encounter: Encounter; side: SeriesSide }>) {
  const t = useTranslations();
  const team = side === "home" ? encounter.home_team : encounter.away_team;
  const meta = [
    team?.placement != null ? `${t("encounters.detail.placementShort")} #${team.placement}` : null,
    team?.group?.name ? `${t("common.group")} ${team.group.name}` : null
  ].filter(Boolean);

  return (
    <div
      className={cn(
        styles.boardSide,
        side === "home" ? styles.sideHome : styles.sideAway,
        side === "away" && styles.boardSideAway
      )}
    >
      <TeamLogo team={team} size="xl" />
      <div className={styles.boardIdentity}>
        {/* Not a heading: a scoreboard label. The h1 above names the matchup. */}
        <p className={styles.boardName}>{team?.name ?? t("common.tbd")}</p>
        {/* Plain text, not chips: the winner is already the verdict and the pips. */}
        {meta.length > 0 ? <p className={styles.boardMeta}>{meta.join(" · ")}</p> : null}
      </div>
    </div>
  );
}

/** Played: a parsed log or an accepted result — the page's own rule. */
function isPlayed(slot: SeriesSlot): boolean {
  return slot.match != null || acceptedScore(slot.game) != null;
}

/**
 * Pip hue, in the same precedence the aria summary below reads out: in-progress
 * first, then never-played, then the winner's side, then a tie.
 */
function pipToneClass(slot: SeriesSlot): string {
  if (slot.isLive) return styles.pipLive;
  if (!isPlayed(slot)) return styles.pipEmpty;
  if (slot.winner === "home") return styles.pipHome;
  if (slot.winner === "away") return styles.pipAway;
  return styles.pipDraw;
}

/**
 * One pip per slot of the format: filled in the winner's hue, hollow for a map
 * the series never needed, ringed for the map in progress. This is what makes a
 * 3–1 in a Bo5 legible as "four maps played, one spare".
 */
function MapPips({ slots }: Readonly<{ slots: SeriesSlot[] }>) {
  const t = useTranslations();
  const summary = slots
    .map((slot) => {
      if (slot.isLive) return t("encounters.state.live");
      if (!isPlayed(slot)) return t("encounters.detail.pipUnplayed");
      if (!slot.winner) return t("encounters.detail.tie");
      return slot.winner === "home" ? t("common.homeTeam") : t("common.awayTeam");
    })
    .join(", ");

  return (
    <div
      className={styles.boardPips}
      role="img"
      aria-label={t("encounters.detail.pipsAria", { summary })}
    >
      {slots.map((slot) => (
        <span key={slot.index} aria-hidden className={cn(styles.pip, pipToneClass(slot))} />
      ))}
    </div>
  );
}
