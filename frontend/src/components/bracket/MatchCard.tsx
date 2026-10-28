"use client";

import { memo, useContext, type HTMLAttributes, type ReactNode } from "react";
import { useDraggable, useDroppable } from "@dnd-kit/core";
import { ListChecks, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import type { BracketMatch } from "@/lib/bracket/view";
import { duelSeats, seatAt, type Duel, type DuelSlot } from "@/lib/encounter/seats";
import { EncounterRostersModal } from "@/components/EncounterRostersModal";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import TeamName from "@/components/TeamName";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { Eyebrow } from "@/components/ui/eyebrow";
import { StatusDot } from "@/components/ui/status-dot";
import { withReturnTo } from "@/lib/auth/return-to";
import { StreamWatchContext } from "@/components/stream/stream-watch";
import { streamEntryKey } from "@/lib/social/stream-platform";
import { cn } from "@/lib/utils";
import type { StreamEntry } from "@/types/stream.types";

import { CARD_HEIGHT, CARD_ROW_HEIGHT, GUTTER_WIDTH, type LayoutNode } from "./layout";

/** A card's frame; the editor's wiring boxes are drawn in it too. Callers add the border colour. */
export const CARD_FRAME =
  "relative flex h-full overflow-hidden rounded-[10px] border bg-[color:var(--aqt-card)] shadow-[0_10px_24px_rgba(0,0,0,0.28)]";

/** The strip of icon controls under a card's two rows. */
export const CARD_FOOTER =
  "flex items-center justify-between gap-1.5 border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-1.5";

/** The strip down a card's left edge: "M" over the match number. `className` swaps the tone. */
export function MatchGutter({
  number,
  className,
  children,
  ...props
}: Readonly<HTMLAttributes<HTMLDivElement> & { number: number }>) {
  return (
    <div
      className={cn(
        "flex shrink-0 flex-col items-center justify-center gap-0.5 border-r border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)] leading-none text-[color:var(--aqt-fg-muted)]",
        className
      )}
      style={{ width: GUTTER_WIDTH }}
      {...props}
    >
      <span className="text-label font-semibold leading-none tracking-label opacity-70">M</span>
      <span className="text-caption font-bold tabular-nums">{number}</span>
      {children}
    </div>
  );
}

/** dnd-kit id of one team slot; the same string names its draggable and its droppable. */
function slotDragId(encounterId: number, slot: DuelSlot) {
  return `slot-${encounterId}-${slot}`;
}

export interface SlotDragData {
  encounterId: number;
  slot: DuelSlot;
  teamId: number | null;
  teamName: string;
}

interface SlotRowProps {
  node: LayoutNode;
  slot: DuelSlot;
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
  slot,
  highlighted,
  onHoverTeam,
  liveTeamStreams,
  draggable,
  rearranging
}: Readonly<SlotRowProps>) {
  const t = useTranslations();
  const watcher = useContext(StreamWatchContext);
  const { data, encounter } = node;
  const seat = slot === 1 ? data.seats.one : data.seats.two;
  const { teamId, name, score, isLatest } = seat;
  const won = data.winner === slot;
  const hasVisibleScore = data.isCompleted || data.seats.one.score !== 0 || data.seats.two.score !== 0;
  // An unfilled slot shows a hint ("W M3") rather than a team, so it gets no
  // logo — `seat.name` is also the source of a name parsed out of the
  // encounter title when the team relation itself is missing.
  const isTbd = name === "TBD";
  const slotTeam = isTbd ? null : (seatAt(encounter.teams, slot)?.team ?? null);
  const displayName = isTbd ? (seat.source ?? t("common.tbd")) : name;

  const dragData: SlotDragData = { encounterId: encounter.id, slot, teamId, teamName: displayName };
  const dragId = slotDragId(encounter.id, slot);
  // A TBD slot can be dropped ON (a team moves into the bye) but never picked up.
  const drag = useDraggable({ id: dragId, data: dragData, disabled: !draggable || teamId === null });
  const drop = useDroppable({ id: dragId, data: dragData, disabled: !draggable });

  // The participant stream on air for this slot's team, shown on the team's
  // newest match only (see `isLatest`) and never once that match is
  // decided. A TBD slot has no team, so it can never carry the indicator.
  const liveStream =
    liveTeamStreams === undefined || isTbd || teamId === null || !isLatest || data.isCompleted
      ? undefined
      : liveTeamStreams.get(teamId);
  // The map only ever holds participant entries, which always carry a player;
  // the channel fallback exists because `player` is nullable on the wire (an
  // official broadcast has none).
  const streamer = liveStream === undefined ? null : (liveStream.player?.name ?? liveStream.channel);
  // Opens the shell's POV dock when there is one. In rearrange mode the row is
  // a drag handle, and outside the tournament shell there is no dock: there
  // the marker stays an indication.
  const canWatch = watcher !== null && !rearranging;
  const liveLabel =
    liveStream === undefined || streamer === null
      ? null
      : liveStream.viewer_count == null
        ? t(canWatch ? "bracket.watchTeamStream" : "bracket.liveTeamStream", { player: streamer })
        : t(canWatch ? "bracket.watchTeamStreamWithViewers" : "bracket.liveTeamStreamWithViewers", {
            player: streamer,
            count: liveStream.viewer_count
          });
  // The site's one liveness language, in its smallest form: the pill's chrome
  // does not fit a 30px row, the pulsing dot does.
  const liveDot = (
    <StatusDot
      pulse
      className="size-[7px] text-[color:var(--aqt-status-live)] shadow-[0_0_0_3px_color-mix(in_srgb,var(--aqt-status-live)_18%,transparent)]"
    />
  );

  const tone =
    data.winner === slot
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
        slot === 1 && "border-b border-[color:var(--aqt-border)]",
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
        {data.floatRecord?.slot === slot ? (
          // Swiss: this team came in with a worse record than the pool the match sits in.
          <span
            className="shrink-0 text-label tabular-nums text-[color:var(--aqt-fg-faint)]"
            title={t("bracket.floatRecord", { record: data.floatRecord.label })}
          >
            {data.floatRecord.label}
          </span>
        ) : null}
        {liveStream !== undefined && liveLabel !== null ? (
          canWatch ? (
            <Button
              type="button"
              variant="ghost"
              size="icon-xs"
              aria-label={liveLabel}
              title={liveLabel}
              // Which side of the match the dock is showing.
              aria-pressed={watcher.watchingKey === streamEntryKey(liveStream)}
              data-live-team-stream={liveStream.channel}
              onClick={(event) => watcher.watch(liveStream, event.currentTarget)}
              // 20px box, 24px hit area through the pseudo-element (WCAG 2.5.8)
              // without growing the fixed-height row. The pressed outline is a
              // shadow so it composes with the primitive's focus ring.
              className="relative shrink-0 rounded-full before:absolute before:-inset-0.5 before:content-[''] hover:bg-[color:color-mix(in_srgb,var(--aqt-status-live)_16%,transparent)] aria-pressed:bg-[color:color-mix(in_srgb,var(--aqt-status-live)_16%,transparent)] aria-pressed:shadow-[inset_0_0_0_1.5px_var(--aqt-status-live)]"
            >
              {liveDot}
            </Button>
          ) : (
            <span
              role="img"
              aria-label={liveLabel}
              title={liveLabel}
              data-live-team-stream={liveStream.channel}
              className="inline-flex shrink-0 items-center"
            >
              {liveDot}
            </span>
          )
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
  /** Which seat's team is the one hovered elsewhere in the tree. */
  highlighted: Duel<boolean>;
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
  highlighted,
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
  const isLive = encounter.is_live === true;
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
        CARD_FRAME,
        isLive
          ? "border-[color:color-mix(in_srgb,var(--aqt-rose)_45%,transparent)]"
          : data.winner
            ? "border-[color:var(--aqt-border-2)]"
            : "border-[color:var(--aqt-border)]"
      )}
    >
      <MatchGutter
        number={data.matchNumber}
        className={
          encounter.result_status === "pending_confirmation"
            ? "border-[color:color-mix(in_srgb,var(--aqt-amber)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-amber)_18%,var(--aqt-bg-2))] text-[color:var(--aqt-amber)]"
            : encounter.result_status === "disputed"
              ? "border-[color:color-mix(in_srgb,var(--aqt-rose)_35%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-rose)_18%,var(--aqt-bg-2))] text-[color:var(--aqt-rose)]"
              : undefined
        }
        title={attention ?? undefined}
        data-result-status={attention === null ? undefined : encounter.result_status}
      >
        {attention !== null && <span className="sr-only">{attention}</span>}
      </MatchGutter>

      <div className="flex min-w-0 flex-1 flex-col">
        <SlotRow {...rowProps} slot={1} highlighted={highlighted.one} />
        <SlotRow {...rowProps} slot={2} highlighted={highlighted.two} />

        <div className={CARD_FOOTER} style={{ height: footerHeight }}>
          {/* Look (view, rosters, pre-game) then act (edit, report), one hairline
              between; the series format keeps the right edge. */}
          <div className="flex min-w-0 items-center gap-0.5">
            {interactive && (
              <>
                <Button asChild variant="ghost" size="icon-xs" className="text-[color:var(--aqt-fg-muted)]">
                  <HoverPrefetchLink
                    href={`/encounters/${encounter.id}`}
                    aria-label={t("bracket.viewMatch")}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <Search aria-hidden />
                  </HoverPrefetchLink>
                </Button>
                {/* The roster peek stays on the bracket: a scroll position built up
                    over a 32-team tree survives looking at who is playing. The
                    pre-game link leaves, because the room is where a captain acts. */}
                <EncounterRostersModal
                  encounterId={encounter.id}
                  teamNames={[
                    duelSeats(encounter.teams)[0]?.name ?? t("common.tbd"),
                    duelSeats(encounter.teams)[1]?.name ?? t("common.tbd")
                  ]}
                />
                <Button asChild variant="ghost" size="icon-xs" className="text-[color:var(--aqt-fg-muted)]">
                  <HoverPrefetchLink
                    href={withReturnTo(`/tournaments/${encounter.tournament_id}/pregame/${encounter.id}`, returnTo)}
                    aria-label={t("bracket.pregameRoom")}
                    onClick={(e) => e.stopPropagation()}
                  >
                    <ListChecks aria-hidden />
                  </HoverPrefetchLink>
                </Button>
              </>
            )}
            {interactive && actions && (
              <Separator orientation="vertical" className="mx-0.5 h-3 bg-[color:var(--aqt-border-2)]" />
            )}
            {actions}
          </div>
          {bestOfLabel && (
            <Eyebrow tone="muted" className="shrink-0">
              {bestOfLabel}
            </Eyebrow>
          )}
        </div>
      </div>
    </div>
  );
});
