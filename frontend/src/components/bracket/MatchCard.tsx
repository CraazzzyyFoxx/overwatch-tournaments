"use client";

import { memo, type ReactNode } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { ListChecks, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import type { BracketMatch } from "@/lib/bracket-view";
import { EncounterRostersModal } from "@/components/EncounterRostersModal";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import TeamName from "@/components/TeamName";
import { withReturnTo } from "@/lib/return-to";
import { STREAM_STATUS_META } from "@/lib/stream-platform";
import { cn } from "@/lib/utils";
import type { StreamEntry } from "@/types/stream.types";

import { CARD_HEIGHT, CARD_ROW_HEIGHT, GUTTER_WIDTH, type LayoutNode, type Side } from "./layout";

/** One footer control: the three viewer links and the admin's edit share it. */
export const FOOTER_BUTTON =
  "flex items-center justify-center rounded p-0.5 text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]";

/** dnd-kit id of one team slot; the same string names its draggable and its droppable. */
export function slotDragId(encounterId: number, side: Side) {
  return `slot-${encounterId}-${side}`;
}

export interface SlotDragData {
  encounterId: number;
  side: Side;
  teamId: number | null;
  teamName: string;
}

interface SlotRowProps {
  node: LayoutNode;
  side: Side;
  highlighted: boolean;
  onHoverTeam: (teamId: number | null) => void;
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  /** Rearrange mode is on AND this match may still have its teams moved. */
  draggable: boolean;
  /** Rearrange mode is on; a locked match still says so on its rows. */
  rearranging: boolean;
}

function SlotRow({
  node,
  side,
  highlighted,
  onHoverTeam,
  liveTeamStreams,
  draggable,
  rearranging
}: Readonly<SlotRowProps>) {
  const t = useTranslations();
  const { data, encounter } = node;
  const teamId = side === "home" ? data.homeTeamId : data.awayTeamId;
  const name = side === "home" ? data.homeName : data.awayName;
  const score = side === "home" ? data.homeScore : data.awayScore;
  const won = data.winner === side;
  const hasVisibleScore = data.isCompleted || data.homeScore !== 0 || data.awayScore !== 0;
  // An unfilled slot shows a hint ("W M3") rather than a team, so it gets no
  // logo — `data.*Name` is also the source of a name parsed out of the
  // encounter title when the team relation itself is missing.
  const isTbd = name === "TBD";
  const slotTeam = isTbd ? null : side === "home" ? encounter.home_team : encounter.away_team;
  const displayName = isTbd
    ? ((side === "home" ? data.homeSource : data.awaySource) ?? t("common.tbd"))
    : name;

  const dragData: SlotDragData = { encounterId: encounter.id, side, teamId, teamName: displayName };
  const dragId = slotDragId(encounter.id, side);
  // A TBD slot can be dropped ON (a team moves into the bye) but never picked up.
  const drag = useDraggable({ id: dragId, data: dragData, disabled: !draggable || teamId === null });
  const drop = useDroppable({ id: dragId, data: dragData, disabled: !draggable });

  // The participant stream on air for this slot's team, shown on the team's
  // newest match only (see `homeIsLatest`) and never once that match is
  // decided. A TBD slot has no team, so it can never carry the indicator.
  const isLatest = side === "home" ? data.homeIsLatest : data.awayIsLatest;
  const liveStream =
    liveTeamStreams === undefined || isTbd || teamId === null || !isLatest || data.isCompleted
      ? undefined
      : liveTeamStreams.get(teamId);
  // The map only ever holds participant entries, which always carry a player;
  // the channel fallback exists because `player` is nullable on the wire (an
  // official broadcast has none).
  const streamer = liveStream === undefined ? null : (liveStream.player?.name ?? liveStream.channel);
  const liveLabel =
    liveStream === undefined || streamer === null
      ? null
      : liveStream.viewer_count == null
        ? t("bracket.liveTeamStream", { player: streamer })
        : t("bracket.liveTeamStreamWithViewers", { player: streamer, count: liveStream.viewer_count });

  const tone =
    data.winner === side
      ? "bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-fg)] font-semibold"
      : data.winner
        ? "text-[color:var(--aqt-fg-dim)]"
        : "text-[color:var(--aqt-fg-muted)]";

  return (
    <div
      ref={(el) => {
        drag.setNodeRef(el);
        drop.setNodeRef(el);
      }}
      className={cn(
        "flex items-center justify-between gap-2 px-2.5 transition-colors",
        side === "home" && "border-b border-[color:var(--aqt-border)]",
        tone,
        highlighted &&
          "bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] text-[color:var(--aqt-fg)]",
        rearranging && !draggable && "opacity-50",
        draggable && teamId !== null && "cursor-grab",
        drag.isDragging && "opacity-40",
        drop.isOver && !drag.isDragging && "ring-2 ring-inset ring-[color:var(--aqt-teal)]"
      )}
      data-team-id={teamId ?? undefined}
      data-team-highlighted={highlighted || undefined}
      data-slot-draggable={draggable && teamId !== null ? "" : undefined}
      onPointerEnter={() => onHoverTeam(teamId)}
      onPointerLeave={() => {
        if (highlighted) onHoverTeam(null);
      }}
      style={{ height: CARD_ROW_HEIGHT }}
      // dnd-kit's activator attributes (role=button, tabIndex, aria-describedby)
      // only in rearrange mode: a spectator's row is not a button.
      {...(draggable && teamId !== null ? { ...drag.attributes, ...drag.listeners } : {})}
      aria-label={draggable && teamId !== null ? t("bracket.dragTeam", { team: displayName }) : undefined}
    >
      {/* Name and dot share one shrinking group so the score stays pinned to
          the right edge — the row is a fixed CARD_ROW_HEIGHT with nowhere to spill. */}
      <span className="flex min-w-0 items-center gap-1.5">
        <TeamName
          team={slotTeam}
          fallback={displayName}
          size="xs"
          nameClassName={isTbd ? "text-label italic text-[color:var(--aqt-fg-faint)]" : "text-caption"}
        />
        {liveStream !== undefined && liveLabel !== null ? (
          <span
            // Indication, NOT navigation: the Streams tab lists every channel as
            // a full-sized link, so this is a labelled image with no href.
            role="img"
            aria-label={liveLabel}
            title={liveLabel}
            data-live-team-stream={liveStream.channel}
            // The site's one liveness language: the pulsing rose `.dot` exists
            // only under `.status-pill.live` in `globals.css`. The inline style
            // strips the pill's own chrome, which does not fit a 30px row.
            className={cn(STREAM_STATUS_META.live.pillClassName, "shrink-0")}
            style={{ padding: 0, border: "none", background: "none" }}
          >
            <span aria-hidden className="dot" />
          </span>
        ) : null}
      </span>
      <span
        className={cn(
          "shrink-0 text-caption font-semibold tabular-nums",
          won ? "text-[color:var(--aqt-teal)]" : "text-[color:var(--aqt-fg-muted)]"
        )}
      >
        {hasVisibleScore ? score : "-"}
      </span>
    </div>
  );
}

export interface MatchCardProps {
  node: LayoutNode;
  homeHighlighted: boolean;
  awayHighlighted: boolean;
  onHoverTeam: (teamId: number | null) => void;
  /** This bracket's own location, so the pre-game room can send viewers back to it. */
  returnTo: string;
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  /** `false` on a projected match: there is no encounter row to link to. */
  interactive: boolean;
  rearranging: boolean;
  /** `rearranging` AND this match's teams may still be moved. */
  draggable: boolean;
  /**
   * Edit/report controls for the footer; `null` for a viewer. A function, not
   * a node: a node is rebuilt on every hover and would defeat the memo below.
   */
  renderActions: (encounter: BracketMatch) => ReactNode;
}

/**
 * One match of the tree. Memoised: a hover over one team re-renders the two
 * cards whose highlight flips, not the sixty-three of a double elimination.
 */
export const MatchCard = memo(function MatchCard({
  node,
  homeHighlighted,
  awayHighlighted,
  onHoverTeam,
  returnTo,
  liveTeamStreams,
  interactive,
  rearranging,
  draggable,
  renderActions
}: Readonly<MatchCardProps>) {
  const t = useTranslations();
  const { data, encounter } = node;
  const isLive = !data.isCompleted && Boolean(encounter.started_at) && !encounter.ended_at;
  // The series format is always worth reading next to the score. When the
  // match is played is the schedule's business, not the card's.
  const bestOfLabel = encounter.best_of ? `Bo${encounter.best_of}` : null;
  const footerHeight = CARD_HEIGHT - CARD_ROW_HEIGHT * 2;
  const actions = renderActions(encounter);

  // A result awaiting confirmation or under dispute tints the gutter; the text
  // stays for the tooltip and the screen reader.
  const attention =
    encounter.result_status === "pending_confirmation"
      ? t("bracket.pending")
      : encounter.result_status === "disputed"
        ? t("bracket.disputed")
        : null;

  const rowProps = { node, onHoverTeam, liveTeamStreams, draggable, rearranging };

  return (
    <div
      className={cn(
        "relative flex h-full overflow-hidden rounded-[10px] border bg-[color:var(--aqt-card)] shadow-[0_10px_24px_rgba(0,0,0,0.28)]",
        isLive
          ? "border-[color:color-mix(in_srgb,var(--aqt-rose)_45%,transparent)]"
          : data.winner
            ? "border-[color:var(--aqt-border-2)]"
            : "border-[color:var(--aqt-border)]"
      )}
    >
      <div
        className={cn(
          "flex shrink-0 flex-col items-center justify-center gap-0.5 border-r leading-none",
          encounter.result_status === "pending_confirmation"
            ? "border-[color:color-mix(in_srgb,var(--aqt-amber)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_18%,var(--aqt-bg-2))] text-[color:var(--aqt-amber)]"
            : encounter.result_status === "disputed"
              ? "border-[color:color-mix(in_srgb,var(--aqt-rose)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_18%,var(--aqt-bg-2))] text-[color:var(--aqt-rose)]"
              : "border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] text-[color:var(--aqt-fg-muted)]"
        )}
        style={{ width: GUTTER_WIDTH }}
        title={attention ?? undefined}
        data-result-status={attention === null ? undefined : encounter.result_status}
      >
        <span className="text-[9px] font-semibold tracking-label opacity-70">M</span>
        <span className="text-caption font-bold tabular-nums">{data.matchNumber}</span>
        {attention !== null && <span className="sr-only">{attention}</span>}
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <SlotRow {...rowProps} side="home" highlighted={homeHighlighted} />
        <SlotRow {...rowProps} side="away" highlighted={awayHighlighted} />

        <div
          className="flex items-center justify-between gap-1.5 border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-1.5"
          style={{ height: footerHeight }}
        >
          {/* Look (view, rosters, pre-game) then act (edit, report), one hairline
              between; the series format keeps the right edge. */}
          <div className="flex min-w-0 items-center gap-0.5">
            {interactive && (
              <>
                <HoverPrefetchLink
                  href={`/encounters/${encounter.id}`}
                  className={FOOTER_BUTTON}
                  aria-label={t("bracket.viewMatch")}
                  onClick={(e) => e.stopPropagation()}
                >
                  <Search className="size-3.5" aria-hidden />
                </HoverPrefetchLink>
                {/* The roster peek stays on the bracket: a scroll position built up
                    over a 32-team tree survives looking at who is playing. The
                    pre-game link leaves, because the room is where a captain acts. */}
                <EncounterRostersModal
                  encounterId={encounter.id}
                  homeTeamName={encounter.home_team?.name ?? t("common.tbd")}
                  awayTeamName={encounter.away_team?.name ?? t("common.tbd")}
                />
                <HoverPrefetchLink
                  href={withReturnTo(`/tournaments/${encounter.tournament_id}/pregame/${encounter.id}`, returnTo)}
                  className={FOOTER_BUTTON}
                  aria-label={t("bracket.pregameRoom")}
                  onClick={(e) => e.stopPropagation()}
                >
                  <ListChecks className="size-3.5" aria-hidden />
                </HoverPrefetchLink>
              </>
            )}
            {interactive && actions && (
              <span aria-hidden className="mx-0.5 h-3 w-px shrink-0 bg-[color:var(--aqt-border-2)]" />
            )}
            {actions}
          </div>
          {bestOfLabel && (
            <span className="shrink-0 text-label font-semibold uppercase tracking-wide text-[color:var(--aqt-fg-muted)]">
              {bestOfLabel}
            </span>
          )}
        </div>
      </div>
    </div>
  );
});
