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
import { formatSeriesClock, type SeriesSlot } from "@/lib/encounter-detail";
import { Pill } from "@/components/match/EncounterAtoms";
import styles from "@/components/match/EncounterDetail.module.css";

interface EncounterMapRowProps {
  slot: SeriesSlot;
  homeName: string;
  awayName: string;
  /** Drives the copy for a slot the format allows but that carries no map. */
  seriesCompleted: boolean;
  tournamentGrid?: DivisionGridVersion | null;
  /** Localized duration unit suffixes for the playtime fact. */
  clockUnits: { h: string; m: string; s: string };
}

/**
 * One map of the series.
 *
 * The old page rendered each map as a 115x230 image tile carrying only the map
 * name, so the per-map score, duration, in-game code, result provenance and log
 * name were reachable only by opening a modal. They are on the row now; the
 * modal is reserved for the full scoreboard.
 *
 * The scoreboard itself is still lazy: a Bo5 must not ship five stat tables in
 * the initial payload for content nobody opened. The query key matches the one
 * the series-statistics panel uses, so whichever loads first warms the other.
 */
export default function EncounterMapRow({
  slot,
  homeName,
  awayName,
  seriesCompleted,
  tournamentGrid,
  clockUnits
}: Readonly<EncounterMapRowProps>) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const match = slot.match;
  const game = slot.game;
  // Two contracts for one position: the game carries the result the encounter
  // stands behind, the match is the parsed log. Rendered as two facts — a
  // parsed score that disagrees with the accepted one is information, not a
  // correction (spec §11).
  const accepted = acceptedScore(game);

  const matchQuery = useQuery({
    queryKey: ["match-detail", match?.id],
    queryFn: () => encounterService.getMatch(match!.id),
    enabled: open && match != null,
    staleTime: 5 * 60_000
  });

  if (!match && game == null) {
    // An empty slot means three different things. Saying "the series ended
    // before this map" while the series is live — or while it is the very map
    // being played — is simply false.
    const inProgress = slot.isLive;
    return (
      <div className={cn(styles.mapRow, inProgress ? styles.mapRowLive : styles.mapRowEmpty)}>
        <span className={styles.mapIndex}>{slot.index}</span>
        <span className={cn(styles.mapThumb, styles.mapThumbPlaceholder)}>
          <ImageOff aria-hidden width={18} height={18} />
        </span>
        <span className={styles.mapIdentity}>
          <span className={styles.mapName}>
            {inProgress
              ? t("encounters.detail.mapInProgress")
              : t("encounters.detail.mapNotPlayed")}
          </span>
          <span className={styles.mapMode}>
            {inProgress
              ? t("encounters.detail.mapInProgressHint")
              : seriesCompleted
                ? t("encounters.detail.mapNotPlayedHint")
                : t("encounters.detail.mapPendingHint")}
          </span>
        </span>
        <span className={cn(styles.mapScore, styles.mono)} aria-hidden>
          —
        </span>
        <span className={styles.mapFacts}>
          {inProgress ? (
            <Pill tone="danger" live className={styles.mapFactWide}>
              {t("encounters.state.live")}
            </Pill>
          ) : null}
        </span>
        <span className={styles.mapAction} />
      </div>
    );
  }

  // The position names its map from the moment it is picked; the parsed log
  // names the same map later. Prefer the match's object when both exist.
  const map = match?.map ?? game?.map ?? null;
  const mapName = map?.name ?? t("encounters.match.mapAlt");
  const duration = match != null ? formatSeriesClock(match.time, clockUnits) : null;
  const shown = accepted ?? (game == null && match != null ? match.score : null);
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
          <Image src={map.image_path} alt="" fill sizes="104px" className={styles.mapThumbImage} />
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

      <span className={styles.mapFacts}>
        {duration ? (
          <span className={styles.mapFact}>
            <span className={styles.label}>{t("encounters.match.playtime")}</span>
            <span className={styles.mapFactValue}>
              <span className={styles.mapFactText}>{duration}</span>
            </span>
          </span>
        ) : null}
        {game?.result_source != null ? (
          <span className={styles.mapFact}>
            <span className={styles.label}>{t("encounters.match.source")}</span>
            <span className={styles.mapFactValue}>
              <span className={styles.mapFactText}>
                {t(`encounters.game.source.${game.result_source}` as never)}
              </span>
            </span>
          </span>
        ) : null}
        {/* The parsed log's own score, next to the accepted one rather than in
            place of it: a log that disagrees is a fact about the log. */}
        {match != null ? (
          <span className={styles.mapFact}>
            <span className={styles.label}>{t("encounters.game.parsedScore")}</span>
            <span className={styles.mapFactValue}>
              <span className={styles.mapFactText}>
                {match.score.home}:{match.score.away}
              </span>
            </span>
          </span>
        ) : null}
        {match?.code ? (
          <span className={styles.mapFact}>
            <span className={styles.label}>{t("encounters.match.code")}</span>
            <span className={styles.mapFactValue}>
              <span className={styles.mapFactText}>{match.code}</span>
            </span>
          </span>
        ) : null}
        {match?.log_name ? (
          <span className={styles.mapFact}>
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
        {map?.in_competitive === false ? (
          <Pill tone="warn" className={styles.mapFactWide}>
            {t("encounters.match.nonCompetitive")}
          </Pill>
        ) : null}
      </span>

      {/* The scoreboard is the parsed log's; a position with a result but no
          log has nothing to open. */}
      <span className={styles.mapAction}>{match == null ? null : (
        <Dialog open={open} onOpenChange={setOpen}>
          {/* Every row's button reads "Scoreboard", so the accessible name has
              to carry the map — otherwise a Bo5 offers five identical buttons. */}
          <DialogTrigger
            className={cn(styles.button, styles.buttonAccent)}
            aria-label={t("encounters.match.openStats", { map: mapName })}
          >
            <BarChart3 aria-hidden width={14} height={14} />
            {t("encounters.detail.openScoreboard")}
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
                  {match.score.home}
                </span>
                <span aria-hidden className={styles.scoreSep}>
                  :
                </span>
                <span className={cn(styles.scoreAway, "text-lg font-bold")}>
                  {match.score.away}
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
      )}</span>
    </div>
  );
}

export type { EncounterMapRowProps };
