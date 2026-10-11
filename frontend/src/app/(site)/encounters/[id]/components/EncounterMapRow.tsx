"use client";

import { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { BarChart3, ExternalLink, ImageOff } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger
} from "@/components/ui/dialog";
import { PageStateCard } from "@/components/ui/page-state-card";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import MatchStatsSection from "@/app/(site)/matches/[id]/components/MatchStatsSection";
import encounterService from "@/services/encounter.service";
import type { DivisionGridVersion } from "@/types/workspace.types";
import { acceptedScore } from "@/components/pick-ban/pick-ban-model";
import { formatSeriesClock, type SeriesSlot } from "@/lib/encounter/detail";
import { Pill } from "@/components/match/EncounterAtoms";
import styles from "@/components/match/EncounterDetail.module.css";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

interface EncounterMapRowProps {
  slot: SeriesSlot;
  homeName: string;
  awayName: string;
  tournamentGrid?: DivisionGridVersion | null;
  /** Localized duration unit suffixes for the playtime. */
  clockUnits: { h: string; m: string; s: string };
}

/**
 * One map of the series, on one line: position, map, the accepted score, the
 * playtime and the log/scoreboard controls. Provenance (who reported it, the
 * lobby code, the log file) lives in the scoreboard dialog, where the log is.
 *
 * The scoreboard itself is lazy: a Bo5 must not ship five stat tables in the
 * initial payload for content nobody opened. The query key matches the one
 * the series-statistics panel uses, so whichever loads first warms the other.
 */
export default function EncounterMapRow({
  slot,
  homeName,
  awayName,
  tournamentGrid,
  clockUnits
}: Readonly<EncounterMapRowProps>) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const match = slot.match;
  const game = slot.game;
  // Two contracts for one position: the game carries the result the encounter
  // stands behind, the match is the parsed log (spec §11).
  const accepted = acceptedScore(game);
  const parsed = slot.parsedScore;

  const matchQuery = useQuery({
    queryKey: encounterQueryKeys.matchDetail(match?.id),
    queryFn: () => encounterService.getMatch(match!.id),
    enabled: open && match != null,
    staleTime: 5 * 60_000
  });

  if (!match && game == null) {
    // The page only hands over an empty position while it is being played.
    return (
      <div className={cn(styles.mapRow, styles.mapRowLive)}>
        <span className={styles.mapIndex}>{slot.index}</span>
        <span className={cn(styles.mapThumb, styles.mapThumbPlaceholder)}>
          <ImageOff aria-hidden width={18} height={18} />
        </span>
        <span className={styles.mapIdentity}>
          <span className={styles.mapName}>{t("encounters.detail.mapInProgress")}</span>
          <span className={styles.mapMode}>
            <Pill tone="danger" live>
              {t("encounters.state.live")}
            </Pill>
          </span>
        </span>
      </div>
    );
  }

  // The position names its map from the moment it is picked; the parsed log
  // names the same map later. Prefer the match's object when both exist.
  const map = match?.map ?? game?.map ?? null;
  const mapName = map?.name ?? t("encounters.match.mapAlt");
  const duration = match != null ? formatSeriesClock(match.time, clockUnits) : null;
  const shown = accepted ?? (game == null ? parsed : null);
  // The log's own score is news only when it is not the score above: a map no
  // one confirmed yet, or a log that disagrees with the confirmed result.
  const parsedDiffers =
    parsed != null &&
    shown !== parsed &&
    (shown == null || shown.home !== parsed.home || shown.away !== parsed.away);
  const scoreLabel =
    shown != null
      ? t("encounters.detail.mapScoreAria", {
          home: homeName,
          away: awayName,
          homeScore: shown.home,
          awayScore: shown.away
        })
      : t("encounters.detail.mapNotPlayed");

  return (
    <div className={cn(styles.mapRow, slot.isLive && styles.mapRowLive)}>
      <span className={styles.mapIndex}>{slot.index}</span>

      <span className={cn(styles.mapThumb, !map && styles.mapThumbPlaceholder)}>
        {map ? (
          <Image src={map.image_path} alt="" fill sizes="80px" className={styles.mapThumbImage} />
        ) : (
          <ImageOff aria-hidden width={18} height={18} />
        )}
      </span>

      <span className={styles.mapIdentity}>
        <span className={styles.mapName}>{mapName}</span>
        <span className={styles.mapMode}>
          {map?.gamemode ? (
            <>
              <Image src={map.gamemode.image_path} alt="" width={14} height={14} aria-hidden />
              {map.gamemode.name}
            </>
          ) : (
            t("encounters.match.gamemodeAlt")
          )}
          {slot.isLive ? (
            <Pill tone="danger" live>
              {t("encounters.state.live")}
            </Pill>
          ) : null}
          {parsedDiffers ? (
            <span className={cn(shown != null && styles.metaWarn)}>
              · {t("encounters.game.parsedScore")}{" "}
              <span className={styles.mono}>
                {parsed.home}:{parsed.away}
              </span>
            </span>
          ) : null}
          {map?.in_competitive === false ? (
            <span className={styles.metaWarn}>· {t("encounters.match.nonCompetitive")}</span>
          ) : null}
        </span>
      </span>

      <span
        data-game-state={game?.state ?? "none"}
        className={cn(
          styles.mapScore,
          shown == null || shown.home === shown.away
            ? styles.mapScoreDraw
            : shown.home > shown.away
              ? styles.mapScoreWin
              : styles.mapScoreLoss
        )}
        aria-label={scoreLabel}
      >
        {shown != null ? (
          <>
            <span>{shown.home}</span>
            <span aria-hidden className={styles.mapScoreSep}>
              :
            </span>
            <span>{shown.away}</span>
          </>
        ) : (
          <span aria-hidden>—</span>
        )}
      </span>

      <span className={styles.mapTime}>{duration}</span>

      {/* The scoreboard is the parsed log's; a position with a result but no
          log has nothing to open. */}
      <span className={styles.mapAction}>
        {match?.log_name ? (
          <MatchLogIndicator
            hasLogs
            logs={[{ matchId: match.id, label: match.map?.name ?? undefined }]}
          />
        ) : null}
        {match == null ? null : (
        <Dialog open={open} onOpenChange={setOpen}>
          {/* Every row's button reads "Scoreboard", so the accessible name has
              to carry the map — otherwise a Bo5 offers five identical buttons. */}
          <DialogTrigger
            className={cn(styles.button, styles.buttonAccent)}
            aria-label={t("encounters.match.openStats", { map: mapName })}
          >
            <BarChart3 aria-hidden width={14} height={14} />
            <span className={styles.mapActionLabel}>{t("encounters.detail.openScoreboard")}</span>
          </DialogTrigger>
          <DialogContent className="flex max-h-[90vh] w-[95vw] max-w-[1100px] flex-col gap-0 overflow-hidden p-0">
            <DialogHeader className={cn(styles.dialogHead, "space-y-0")}>
              <DialogTitle className={styles.dialogTitle}>
                {match.map?.gamemode ? (
                  <Image
                    src={match.map.gamemode.image_path}
                    alt=""
                    width={26}
                    height={26}
                    aria-hidden
                  />
                ) : null}
                {mapName}
              </DialogTitle>
              <span className={styles.dialogScore}>
                <span className={cn(styles.dialogTeam, styles.scoreHome)}>{homeName}</span>
                <span className={cn(styles.scoreHome, "text-lg font-bold")}>
                  {parsed?.home}
                </span>
                <span aria-hidden className={styles.scoreSep}>
                  :
                </span>
                <span className={cn(styles.scoreAway, "text-lg font-bold")}>
                  {parsed?.away}
                </span>
                <span className={cn(styles.dialogTeam, styles.scoreAway)}>{awayName}</span>
              </span>
              <span className={styles.dialogFacts}>
                {duration ? (
                  <span className={styles.dialogFact}>
                    <span className={styles.label}>{t("encounters.match.playtime")}</span>
                    <span className={styles.mapFactValue}>{duration}</span>
                  </span>
                ) : null}
                {game?.result_source != null ? (
                  <span className={styles.dialogFact}>
                    <span className={styles.label}>{t("encounters.match.source")}</span>
                    <span className={styles.mapFactValue}>
                      {t(`encounters.game.source.${game.result_source}` as never)}
                    </span>
                  </span>
                ) : null}
                {match.code ? (
                  <span className={styles.dialogFact}>
                    <span className={styles.label}>{t("encounters.match.code")}</span>
                    <span className={styles.mapFactValue}>{match.code}</span>
                  </span>
                ) : null}
                {match.log_name ? (
                  <span className={styles.dialogFact}>
                    <span className={styles.label}>{t("encounters.match.logName")}</span>
                    <span className={styles.mapFactValue}>
                      <span className={styles.mapFactText}>{match.log_name}</span>
                      <MatchLogIndicator
                        hasLogs
                        logs={[{ matchId: match.id, label: match.map?.name ?? undefined }]}
                      />
                    </span>
                  </span>
                ) : null}
                <Link
                  href={`/matches/${match.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={styles.dialogLink}
                >
                  <ExternalLink aria-hidden width={14} height={14} />
                  <span className="hidden sm:inline">{t("encounters.match.openNewTab")}</span>
                </Link>
              </span>
            </DialogHeader>
            <div className={styles.dialogBody}>
              {matchQuery.isError ? (
                <PageStateCard state="error" onAction={() => void matchQuery.refetch()} />
              ) : matchQuery.data ? (
                <MatchStatsSection match={matchQuery.data} tournamentGrid={tournamentGrid} />
              ) : (
                <div className="flex flex-col gap-2" aria-busy>
                  {Array.from({ length: 8 }).map((_, index) => (
                    <span key={index} className={cn(styles.skeleton, "h-10 w-full")} />
                  ))}
                </div>
              )}
            </div>
          </DialogContent>
        </Dialog>
        )}
      </span>
    </div>
  );
}

export type { EncounterMapRowProps };
