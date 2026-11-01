"use client";

import Image from "@/components/ui/image";
import { useTranslations } from "next-intl";
import { BarChart3, ImageOff } from "lucide-react";

import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { StatusDot } from "@/components/ui/status-dot";
import MatchLogIndicator from "@/components/match/MatchLogIndicator";
import MatchStatsDialog from "@/components/match/MatchStatsDialog";
import { ScoreCell, type ScoreKind } from "@/components/match/cells";
import {
  CARD_SUB,
  MAP_ACTION,
  MAP_IDENTITY,
  MAP_INDEX,
  MAP_ROW,
  MAP_SCORE,
  MAP_THUMB,
  MAP_TIME
} from "@/components/match/EncounterAtoms";
import { acceptedScore } from "@/components/pick-ban/pick-ban-model";
import { formatSeriesClock, type SeriesSlot } from "@/lib/encounter/detail";
import type { Duel } from "@/lib/encounter/seats";
import type { Encounter } from "@/types/encounter.types";
import { Badge } from "@/components/ui/badge";

/** The map on air keeps its tint under the pointer; every other row takes the row hover. */
const LIVE_ROW = "bg-[color:color-mix(in_srgb,var(--aqt-status-live)_5%,transparent)]";
const ROW_HOVER = "hover:bg-[color:var(--aqt-overlay-2)]";
const THUMB_PLACEHOLDER = "grid place-items-center text-[color:var(--aqt-fg-faint)]";
const MAP_NAME = "font-display text-ui font-semibold wrap-anywhere text-[color:var(--aqt-fg)]";
const MAP_MODE = cn(CARD_SUB, "inline-flex flex-wrap items-center gap-1.5");
const META_WARN = "text-[color:var(--aqt-amber)]";
const SCORE_SEP = "text-label text-[color:var(--aqt-fg-faint)]";

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
  const match = slot.match;
  const game = slot.game;
  // Two contracts for one position: the game carries the result the encounter
  // stands behind, the match is the parsed log (spec §11).
  const accepted = acceptedScore(game, teams);
  const parsed = slot.parsedScore;

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
          <MatchStatsDialog
            matchId={match.id}
            summary={match}
            names={names}
            score={parsed}
            game={game}
            trigger={
              // Every row's button reads "Scoreboard", so the accessible name has
              // to carry the map — otherwise a Bo5 offers five identical buttons.
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
            }
          />
        )}
      </span>
    </div>
  );
}

export type { EncounterMapRowProps };
