import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";
import type { Encounter } from "@/types/encounter.types";
import { TeamLogo } from "@/components/TeamName";
import {
  buildSeriesSlots,
  getSeriesVerdict,
  type SeriesSide,
  type SeriesSlot
} from "@/lib/encounter-detail";
import { Pill, PillFact } from "@/components/match/EncounterAtoms";
import styles from "@/components/match/EncounterDetail.module.css";

/**
 * The series result, stated once and unambiguously.
 *
 * Replaces the old three-card row whose middle card printed "Winner / Loser"
 * above two bare numbers with no indication of the format, of how the maps fell,
 * or of which map is currently being played.
 */
export default function EncounterScoreboard({ encounter }: Readonly<{ encounter: Encounter }>) {
  const t = useTranslations();
  const slots = buildSeriesSlots(encounter);
  const verdict = getSeriesVerdict(encounter);

  return (
    <div className={styles.card}>
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
                  team:
                    verdict.winner === "home"
                      ? (encounter.home_team?.name ?? t("common.tbd"))
                      : (encounter.away_team?.name ?? t("common.tbd"))
                })
              : verdict.outcome === "draw"
                ? t("encounters.detail.verdictDraw")
                : t("encounters.detail.verdictPending")}
          </p>
          <MapPips slots={slots} />
        </div>
        <TeamBlock encounter={encounter} side="away" />
      </div>
    </div>
  );
}

function TeamBlock({ encounter, side }: Readonly<{ encounter: Encounter; side: SeriesSide }>) {
  const t = useTranslations();
  const team = side === "home" ? encounter.home_team : encounter.away_team;
  const name = team?.name ?? t("common.tbd");
  const verdict = getSeriesVerdict(encounter);
  const isWinner = verdict.winner === side;

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
        {/* Deliberately not a heading. These are scoreboard labels, not section
            titles — as <h2>s they injected two context-free entries ("Onyx
            Vanguard", "Crimson Halo") into the document outline ahead of the
            real section headings. The band is named by its section's label. */}
        <p className={styles.boardName}>{name}</p>
        <div className={styles.boardTags}>
          {isWinner ? <Pill tone="good">{t("encounters.detail.winner")}</Pill> : null}
          {verdict.outcome === "win" && verdict.loser === side ? (
            <Pill>{t("encounters.detail.loser")}</Pill>
          ) : null}
          <Pill>{side === "home" ? t("common.homeTeam") : t("common.awayTeam")}</Pill>
          {team?.placement != null ? (
            <PillFact label={t("encounters.detail.placementShort")} value={`#${team.placement}`} />
          ) : null}
          {team?.group?.name ? (
            <PillFact label={t("common.group")} value={team.group.name} />
          ) : null}
        </div>
      </div>
    </div>
  );
}

/**
 * Pip hue, in the same precedence the aria summary below reads out: in-progress
 * first, then never-played, then the winner's side, then a tie.
 */
function pipToneClass(slot: SeriesSlot): string {
  if (slot.isLive) return styles.pipLive;
  if (!slot.match) return styles.pipEmpty;
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
      if (!slot.match) return t("encounters.detail.pipUnplayed");
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
