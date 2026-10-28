"use client";

import { useState } from "react";
import Image from "@/components/ui/image";
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
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/eyebrow";
import { PageStateCard } from "@/components/ui/page-state-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusDot } from "@/components/ui/status-dot";
import MatchLogIndicator, { RawLogStatus } from "@/components/match/MatchLogIndicator";
import MatchStatistics from "@/components/match/MatchStatistics";
import { ScoreCell, type ScoreKind } from "@/components/match/cells";
import {
  CARD_SUB,
  MAP_ACTION,
  MAP_IDENTITY,
  MAP_INDEX,
  MAP_ROW,
  MAP_SCORE,
  MAP_THUMB,
  MAP_TIME,
  SIDE_TEXT
} from "@/components/match/EncounterAtoms";
import encounterService from "@/services/encounter.service";
import { acceptedScore } from "@/components/pick-ban/pick-ban-model";
import { formatSeriesClock, type SeriesSlot } from "@/lib/encounter/detail";
import { mapWithModeName } from "@/lib/catalog/mode";
import type { Duel } from "@/lib/encounter/seats";
import type { Encounter } from "@/types/encounter.types";
import { Badge } from "@/components/ui/badge";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";

/** The map on air keeps its tint under the pointer; every other row takes the row hover. */
const LIVE_ROW = "bg-[color:color-mix(in_srgb,var(--aqt-status-live)_5%,transparent)]";
const ROW_HOVER = "hover:bg-[color:var(--aqt-overlay-2)]";
const THUMB_PLACEHOLDER = "grid place-items-center text-[color:var(--aqt-fg-faint)]";
const MAP_NAME = "font-display text-ui font-semibold wrap-anywhere text-[color:var(--aqt-fg)]";
const MAP_MODE = cn(CARD_SUB, "inline-flex flex-wrap items-center gap-1.5");
const META_WARN = "text-[color:var(--aqt-amber)]";
const SCORE_SEP = "text-label text-[color:var(--aqt-fg-faint)]";
const DIALOG_FACT = "inline-flex min-w-0 items-center gap-1.5";
const DIALOG_FACT_VALUE = "inline-flex min-w-0 items-center gap-1.5 text-[color:var(--aqt-fg-muted)]";
const DIALOG_TEAM = "max-w-44 truncate text-caption font-semibold";

interface EncounterMapRowProps {
  slot: SeriesSlot;
  names: Duel<string>;
  teams: Encounter["teams"];
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
  names,
  teams,
  clockUnits
}: Readonly<EncounterMapRowProps>) {
  const t = useTranslations();
  const [open, setOpen] = useState(false);
  const match = slot.match;
  const game = slot.game;
  // Two contracts for one position: the game carries the result the encounter
  // stands behind, the match is the parsed log (spec §11).
  const accepted = acceptedScore(game, teams);
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
      <div className={cn(MAP_ROW, "transition-colors", LIVE_ROW)}>
        <span className={MAP_INDEX}>{slot.index}</span>
        <span className={cn(MAP_THUMB, THUMB_PLACEHOLDER)}>
          <ImageOff aria-hidden width={18} height={18} />
        </span>
        <span className={MAP_IDENTITY}>
          <span className={MAP_NAME}>{t("encounters.detail.mapInProgress")}</span>
          <span className={MAP_MODE}>
            <Badge shape="pill" tone="danger">
              <StatusDot pulse />
              {t("encounters.state.live")}
            </Badge>
          </span>
        </span>
      </div>
    );
  }

  // The position names its map from the moment it is picked; the parsed log
  // names the same map later. Prefer the match's object when both exist.
  const map = match?.map ?? game?.map ?? null;
  const mapName = map?.name ?? t("encounters.match.mapAlt");
  // The match's own mode: a map several modes share (Deadlock's Midtown) has no parent to name it.
  const mode = match?.mode ?? game?.mode ?? map?.parent ?? null;
  const duration = match != null ? formatSeriesClock(match.duration_s, clockUnits) : null;
  const shown = accepted ?? (game == null ? parsed : null);
  // The log's own score is news only when it is not the score above: a map no
  // one confirmed yet, or a log that disagrees with the confirmed result.
  const parsedDiffers =
    parsed != null &&
    shown !== parsed &&
    (shown == null || shown.one !== parsed.one || shown.two !== parsed.two);
  const scoreLabel =
    shown != null
      ? t("encounters.detail.mapScoreAria", {
          first: names.one,
          second: names.two,
          firstScore: shown.one,
          secondScore: shown.two
        })
      : t("encounters.detail.mapNotPlayed");
  const scoreKind: ScoreKind =
    shown == null || shown.one === shown.two ? "draw" : shown.one > shown.two ? "win" : "loss";

  return (
    <div className={cn(MAP_ROW, "transition-colors", slot.isLive ? LIVE_ROW : ROW_HOVER)}>
      <span className={MAP_INDEX}>{slot.index}</span>

      <span className={cn(MAP_THUMB, !map?.image_path && THUMB_PLACEHOLDER)}>
        {map?.image_path ? (
          <Image src={map.image_path} alt="" fill sizes="80px" className="object-cover" />
        ) : (
          <ImageOff aria-hidden width={18} height={18} />
        )}
      </span>

      <span className={MAP_IDENTITY}>
        <span className={MAP_NAME}>{mapName}</span>
        <span className={MAP_MODE}>
          {mode ? (
            <>
              {mode.image_path ? (
                <Image src={mode.image_path} alt="" width={14} height={14} aria-hidden />
              ) : null}
              {mode.name}
            </>
          ) : (
            t("encounters.match.gamemodeAlt")
          )}
          {slot.isLive ? (
            <Badge shape="pill" tone="danger">
              <StatusDot pulse />
              {t("encounters.state.live")}
            </Badge>
          ) : null}
          {parsedDiffers ? (
            <span className={cn(shown != null && META_WARN)}>
              · {t("encounters.game.parsedScore")}{" "}
              <span className="aqt-tnum">
                {parsed.one}:{parsed.two}
              </span>
            </span>
          ) : null}
          {map?.attrs.in_competitive === false ? (
            <span className={META_WARN}>· {t("encounters.match.nonCompetitive")}</span>
          ) : null}
        </span>
      </span>

      <span data-game-state={game?.state ?? "none"} className={MAP_SCORE} aria-label={scoreLabel}>
        {shown != null ? (
          <>
            <ScoreCell kind={scoreKind} value={String(shown.one)} />
            <span aria-hidden className={SCORE_SEP}>
              :
            </span>
            <ScoreCell kind={scoreKind} value={String(shown.two)} />
          </>
        ) : (
          <span aria-hidden className="aqt-tnum text-ui font-bold text-[color:var(--aqt-amber)]">
            —
          </span>
        )}
      </span>

      <span className={MAP_TIME}>{duration}</span>

      {/* The scoreboard is the parsed log's; a position with a result but no
          log has nothing to open. */}
      <span className={MAP_ACTION}>
        {match?.raw_available ? (
          <MatchLogIndicator
            hasLogs
            logs={[{ matchId: match.id, label: match.map?.name ?? undefined, rawAvailable: match.raw_available }]}
          />
        ) : null}
        {match == null ? null : (
        <Dialog open={open} onOpenChange={setOpen}>
          {/* Every row's button reads "Scoreboard", so the accessible name has
              to carry the map — otherwise a Bo5 offers five identical buttons. */}
          <DialogTrigger asChild>
            <Button
              variant="accent"
              size="sm"
              aria-label={t("encounters.match.openStats", { map: mapName })}
            >
              <BarChart3 aria-hidden />
              {/* Icon only below `md`: the button keeps its map-naming
                  aria-label, and the label's width belongs to the map name. */}
              <span className="hidden md:inline">{t("encounters.detail.openScoreboard")}</span>
            </Button>
          </DialogTrigger>
          <DialogContent variant="panel" className="max-h-[90vh] w-[95vw] max-w-[1100px]">
            <DialogHeader variant="panel">
              <DialogTitle className="flex items-center gap-2.5">
                {mode?.image_path ? (
                  <Image
                    src={mode.image_path}
                    alt=""
                    width={26}
                    height={26}
                    aria-hidden
                  />
                ) : null}
                {mapWithModeName(match.map, match.mode) ?? mapName}
              </DialogTitle>
              <div className="flex flex-wrap items-center gap-x-4.5 gap-y-2">
                <span className="aqt-tnum flex items-center gap-2">
                  <span className={cn(DIALOG_TEAM, SIDE_TEXT[1])}>{names.one}</span>
                  <span className={cn("text-heading font-bold", SIDE_TEXT[1])}>{parsed?.one}</span>
                  <span aria-hidden className={SCORE_SEP}>
                    :
                  </span>
                  <span className={cn("text-heading font-bold", SIDE_TEXT[2])}>{parsed?.two}</span>
                  <span className={cn(DIALOG_TEAM, SIDE_TEXT[2])}>{names.two}</span>
                </span>
                <span className={cn(CARD_SUB, "ms-auto flex flex-wrap items-center gap-x-3.5 gap-y-1.5")}>
                  {duration ? (
                    <span className={DIALOG_FACT}>
                      <Eyebrow>{t("encounters.match.playtime")}</Eyebrow>
                      <span className={DIALOG_FACT_VALUE}>{duration}</span>
                    </span>
                  ) : null}
                  {game?.result_source != null ? (
                    <span className={DIALOG_FACT}>
                      <Eyebrow>{t("encounters.match.source")}</Eyebrow>
                      <span className={DIALOG_FACT_VALUE}>
                        {t(`encounters.game.source.${game.result_source}` as never)}
                      </span>
                    </span>
                  ) : null}
                  {match.log_name ? (
                    <span className={DIALOG_FACT}>
                      <Eyebrow>{t("encounters.match.logName")}</Eyebrow>
                      <span className={DIALOG_FACT_VALUE}>
                        <span className="truncate">{match.log_name}</span>
                      </span>
                    </span>
                  ) : null}
                  <span className={DIALOG_FACT}>
                    <RawLogStatus raw_status={match.raw_status} raw_available={match.raw_available} />
                    {match.raw_available ? (
                      <MatchLogIndicator
                        hasLogs
                        logs={[{ matchId: match.id, label: match.map?.name ?? undefined, rawAvailable: match.raw_available }]}
                      />
                    ) : null}
                  </span>
                  <Link
                    href={`/matches/${match.id}`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 font-semibold text-[color:var(--aqt-teal)] transition-colors hover:underline"
                  >
                    <ExternalLink aria-hidden width={14} height={14} />
                    <span className="hidden sm:inline">{t("encounters.match.openNewTab")}</span>
                  </Link>
                </span>
              </div>
            </DialogHeader>
            <div className="flex-1 overflow-y-auto p-4">
              {matchQuery.isError ? (
                <PageStateCard state="error" onAction={() => void matchQuery.refetch()} />
              ) : matchQuery.data ? (
                <MatchStatistics match={matchQuery.data} />
              ) : (
                <div className="flex flex-col gap-2" aria-busy>
                  {Array.from({ length: 8 }).map((_, index) => (
                    <Skeleton key={index} className="h-10 w-full" />
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
