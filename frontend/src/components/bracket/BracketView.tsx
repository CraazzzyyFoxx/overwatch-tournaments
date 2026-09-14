"use client";

import { useCallback, useMemo, useState } from "react";
import {
  closestCenter,
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  pointerWithin,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
  type KeyboardCoordinateGetter
} from "@dnd-kit/core";
import { FileEdit, Maximize2, Minus, Move, Pencil, Plus, Scan } from "lucide-react";
import { usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  activeRoundNumber,
  orderEliminationRounds,
  type BracketMatch
} from "@/components/bracket-view.helpers";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { cn } from "@/lib/utils";
import type { StreamEntry } from "@/types/stream.types";
import type { StageType } from "@/types/tournament.types";

import { BracketCanvas } from "./BracketCanvas";
import { FOOTER_BUTTON, type SlotDragData } from "./MatchCard";
import { buildLayout, type Side } from "./layout";
import { MAX_SCALE, MIN_SCALE, useBracketViewport } from "./useBracketViewport";

/** One team slot of one match, as the rearrange callback names it. */
export interface BracketSlotRef<M extends BracketMatch = BracketMatch> {
  encounter: M;
  slot: Side;
}

/**
 * Generic over the row type so an action handler can keep taking the caller's
 * OWN match type: the public bracket's `onEdit` needs a full `Encounter`, and a
 * callback typed on the wider `BracketMatch` would not accept it (parameters
 * are contravariant). The layout stays non-generic — it reads only
 * `BracketMatch` fields — so the handoff back to `M` happens where these
 * callbacks are invoked.
 */
export interface BracketViewProps<M extends BracketMatch> {
  encounters: M[];
  type: StageType;
  onEdit?: (encounter: M) => void;
  onReport?: (encounter: M) => void;
  canEdit?: (encounter: M) => boolean;
  canReport?: (encounter: M) => boolean;
  /**
   * Exchange the teams in two slots. Present → the toolbar offers a rearrange
   * mode in which team rows drag onto one another; settled and live matches
   * stay locked (`isSlotRearrangeable`). The caller owns the request and the
   * cache; the view only waits for the promise to release the drag.
   */
  onSwapSlots?: (source: BracketSlotRef<M>, target: BracketSlotRef<M>) => Promise<unknown> | void;
  /**
   * Team id → the stream of whoever from that team is on air, keyed by the same
   * id `Encounter.home_team_id`/`away_team_id` carry.
   *
   * Optional on purpose: this component is shared with the admin bracket, which
   * has no stream query behind it.
   */
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  /**
   * Whether a card links out (match page, rosters, pre-game room). Off for the
   * admin bracket preview, whose matches are the generator's skeleton and have
   * no encounter row to link to yet.
   */
  interactive?: boolean;
  /**
   * Encounter id to bring into view and outline on mount — the `?match=` deep
   * link the overview and matches sections use to point at one node.
   */
  highlightMatchId?: number | null;
}

const TOOL_BUTTON =
  "inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_0%/0.6)] text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)] disabled:cursor-not-allowed disabled:opacity-40";

/**
 * Keyboard drags jump slot to slot: an arrow lands the picked-up team on the
 * nearest droppable row in that direction, instead of dnd-kit's 25px nudges
 * across a 258px column pitch.
 */
const ARROW_DIRECTION: Record<string, readonly [number, number]> = {
  ArrowRight: [1, 0],
  ArrowLeft: [-1, 0],
  ArrowUp: [0, -1],
  ArrowDown: [0, 1]
};

const slotKeyboardCoordinates: KeyboardCoordinateGetter = (
  event,
  { context: { active, collisionRect, droppableRects, droppableContainers } }
) => {
  const direction = ARROW_DIRECTION[event.key];
  if (!direction || !active || !collisionRect) return undefined;
  event.preventDefault();
  const cx = collisionRect.left + collisionRect.width / 2;
  const cy = collisionRect.top + collisionRect.height / 2;
  let best: { x: number; y: number } | undefined;
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const container of droppableContainers.getEnabled()) {
    if (container.id === active.id) continue;
    const rect = droppableRects.get(container.id);
    if (!rect) continue;
    const dx = rect.left + rect.width / 2 - cx;
    const dy = rect.top + rect.height / 2 - cy;
    const along = dx * direction[0] + dy * direction[1];
    if (along <= 1) continue;
    // Straying off-axis costs double, so "right" prefers the same row's column
    // over a diagonal neighbour.
    const distance = along + 2 * (Math.abs(dx * direction[1]) + Math.abs(dy * direction[0]));
    if (distance < bestDistance) {
      bestDistance = distance;
      best = { x: rect.left, y: rect.top };
    }
  }
  return best;
};

// Pointer drags drop only on the row under the cursor; a keyboard drag has no
// cursor, so it takes the row its rect was moved onto.
const slotCollision: CollisionDetection = (args) =>
  args.pointerCoordinates ? pointerWithin(args) : closestCenter(args);

export function BracketView<M extends BracketMatch>({
  encounters,
  type,
  onEdit,
  onReport,
  canEdit,
  canReport,
  onSwapSlots,
  liveTeamStreams,
  interactive = true,
  highlightMatchId = null
}: Readonly<BracketViewProps<M>>) {
  const t = useTranslations();
  // The bracket's own location, stage/view query included: the pre-game room
  // carries it so its back button and its final report land the viewer back on
  // the exact tab they left, not on a single encounter's page.
  const pathname = usePathname();
  const search = useSearchParams()?.toString();
  const returnTo = search ? `${pathname}?${search}` : pathname;
  const [hoveredTeamId, setHoveredTeamId] = useState<number | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [isRearranging, setIsRearranging] = useState(false);
  const [dragging, setDragging] = useState<SlotDragData | null>(null);
  const [isSwapping, setIsSwapping] = useState(false);

  // The tree draws the upper bracket as its own labelled row of columns, so a
  // "UB " prefix on every header repeats what the picture already says.
  const roundLabel = useBracketRoundLabel({ bareUpper: true });
  const layout = useMemo(() => buildLayout(encounters, type, roundLabel), [encounters, type, roundLabel]);

  // Where the tree opens when nothing is deep-linked: the top-left corner of
  // the round in play. A finished round 1 is not what a viewer came for, and
  // the canvas is routinely wider than the viewport.
  const focus = useMemo(() => {
    if (highlightMatchId !== null) return null;
    const round = activeRoundNumber(orderEliminationRounds(encounters, type).groups);
    if (round === null) return null;
    const column = layout.nodes.filter((node) => node.encounter.round === round);
    if (column.length === 0) return null;
    return {
      x: Math.min(...column.map((node) => node.x)),
      y: Math.min(...column.map((node) => node.y))
    };
  }, [encounters, type, layout.nodes, highlightMatchId]);

  const viewport = useBracketViewport({ layoutWidth: layout.width, focus });

  const byId = useMemo(() => new Map(encounters.map((match) => [match.id, match])), [encounters]);
  const sensors = useSensors(
    // Six pixels of intent before a drag starts, so a click on a row still hovers
    // and a pan started on the card frame does not pick the team up.
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: slotKeyboardCoordinates })
  );
  const onDragStart = useCallback((event: DragStartEvent) => {
    setDragging((event.active.data.current as SlotDragData | undefined) ?? null);
  }, []);
  const onDragEnd = useCallback(
    async (event: DragEndEvent) => {
      setDragging(null);
      const source = event.active.data.current as SlotDragData | undefined;
      const target = event.over?.data.current as SlotDragData | undefined;
      if (!onSwapSlots || !source || !target || event.active.id === event.over?.id) return;
      const sourceMatch = byId.get(source.encounterId);
      const targetMatch = byId.get(target.encounterId);
      if (!sourceMatch || !targetMatch) return;
      setIsSwapping(true);
      try {
        await onSwapSlots(
          { encounter: sourceMatch, slot: source.side },
          { encounter: targetMatch, slot: target.side }
        );
      } finally {
        setIsSwapping(false);
      }
    },
    [byId, onSwapSlots]
  );

  // Stable across a hover: `MatchCard` is memoised on it (see its prop doc).
  const renderActions = useCallback(
    (encounter: BracketMatch) => {
      // Every node was built from `encounters: M[]`, so its row IS an `M`.
      const match = encounter as M;
      const editable = onEdit && (canEdit?.(match) ?? true);
      const reportable = onReport && (canReport?.(match) ?? false);
      if (!editable && !reportable) return null;
      return (
        <>
          {editable && (
            <button
              type="button"
              className={FOOTER_BUTTON}
              aria-label={t("bracket.editMatch")}
              onClick={(e) => {
                e.stopPropagation();
                onEdit?.(match);
              }}
            >
              <Pencil className="size-3.5" aria-hidden />
            </button>
          )}
          {reportable && (
            <button
              type="button"
              className="flex items-center justify-center rounded-[5px] border border-[color:color-mix(in_srgb,var(--aqt-teal)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] p-0.5 text-[color:var(--aqt-teal)] transition-colors hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_24%,transparent)]"
              aria-label={t("bracket.reportMatch")}
              onClick={(e) => {
                e.stopPropagation();
                onReport?.(match);
              }}
            >
              <FileEdit className="size-3" aria-hidden />
            </button>
          )}
        </>
      );
    },
    [t, onEdit, onReport, canEdit, canReport]
  );

  if (layout.nodes.length === 0) {
    return <div className="py-8 text-center text-muted-foreground">{t("common.noBracketMatches")}</div>;
  }

  const bracketTitle =
    type === "double_elimination"
      ? t("bracket.doubleElimination")
      : type === "single_elimination"
        ? t("bracket.singleElimination")
        : t("common.bracket");

  const toolbar = (fullscreen: boolean) => (
    <div className="flex items-center gap-1.5" role="toolbar" aria-label={t("bracket.toolbar")}>
      <button
        type="button"
        className={TOOL_BUTTON}
        onClick={viewport.zoomOut}
        disabled={viewport.scale <= MIN_SCALE}
        aria-label={t("bracket.zoomOut")}
        title={t("bracket.zoomOut")}
      >
        <Minus className="h-4 w-4" aria-hidden />
      </button>
      <span className="min-w-10 text-center text-label tabular-nums text-[color:var(--aqt-fg-muted)]" aria-live="polite">
        {Math.round(viewport.scale * 100)}%
      </span>
      <button
        type="button"
        className={TOOL_BUTTON}
        onClick={viewport.zoomIn}
        disabled={viewport.scale >= MAX_SCALE}
        aria-label={t("bracket.zoomIn")}
        title={t("bracket.zoomIn")}
      >
        <Plus className="h-4 w-4" aria-hidden />
      </button>
      <button
        type="button"
        className={TOOL_BUTTON}
        onClick={viewport.fit}
        aria-label={t("bracket.zoomFit")}
        title={t("bracket.zoomFit")}
      >
        <Scan className="h-4 w-4" aria-hidden />
      </button>
      {onSwapSlots ? (
        <button
          type="button"
          className={cn(
            TOOL_BUTTON,
            isRearranging && "border-[color:var(--aqt-teal)] text-[color:var(--aqt-teal)]"
          )}
          onClick={() => setIsRearranging((value) => !value)}
          aria-pressed={isRearranging}
          aria-label={t("bracket.rearrange")}
          title={t("bracket.rearrange")}
          data-bracket-rearrange
        >
          <Move className="h-4 w-4" aria-hidden />
        </button>
      ) : null}
      {fullscreen ? null : (
        <button
          type="button"
          className={TOOL_BUTTON}
          onClick={() => setIsFullscreen(true)}
          aria-label={t("common.bracketFullscreen")}
          title={t("common.bracketFullscreen")}
        >
          <Maximize2 className="h-4.5 w-4.5" aria-hidden />
        </button>
      )}
    </div>
  );

  // One canvas, wherever it currently lives. Context flows through the dialog's
  // portal, so the drag context can wrap it here.
  const canvas = (fullscreen: boolean) => (
    <DndContext
      sensors={sensors}
      collisionDetection={slotCollision}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragging(null)}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) =>
            t("bracket.dnd.pickedUp", { team: (active.data.current as SlotDragData).teamName }),
          onDragOver: ({ active, over }) =>
            over
              ? t("bracket.dnd.over", {
                  team: (active.data.current as SlotDragData).teamName,
                  slot: (over.data.current as SlotDragData).teamName
                })
              : t("bracket.dnd.overNothing", { team: (active.data.current as SlotDragData).teamName }),
          onDragEnd: ({ active, over }) =>
            over
              ? t("bracket.dnd.dropped", {
                  team: (active.data.current as SlotDragData).teamName,
                  slot: (over.data.current as SlotDragData).teamName
                })
              : t("bracket.dnd.cancelled", { team: (active.data.current as SlotDragData).teamName }),
          onDragCancel: ({ active }) =>
            t("bracket.dnd.cancelled", { team: (active.data.current as SlotDragData).teamName })
        },
        screenReaderInstructions: { draggable: t("bracket.dnd.instructions") }
      }}
    >
      <div aria-busy={isSwapping || undefined} className="contents">
        <BracketCanvas
          layout={layout}
          scale={viewport.scale}
          isGrabbing={viewport.isGrabbing}
          attachScroller={viewport.attachScroller}
          scrollerHandlers={viewport.scrollerHandlers}
          fullscreen={fullscreen}
          hoveredTeamId={hoveredTeamId}
          onHoverTeam={setHoveredTeamId}
          returnTo={returnTo}
          liveTeamStreams={liveTeamStreams}
          interactive={interactive}
          highlightMatchId={highlightMatchId}
          rearranging={isRearranging && !!onSwapSlots && !isSwapping}
          renderActions={renderActions}
        />
      </div>
      <DragOverlay dropAnimation={null}>
        {dragging ? (
          <div className="rounded-md border border-[color:var(--aqt-teal)] bg-[color:var(--aqt-card)] px-2.5 py-1 text-caption font-semibold text-[color:var(--aqt-fg)] shadow-[0_10px_24px_rgba(0,0,0,0.4)]">
            {dragging.teamName}
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );

  const rearrangeHint =
    isRearranging && onSwapSlots ? (
      <p
        className="pointer-events-none max-w-[60%] rounded-lg border border-[color:color-mix(in_srgb,var(--aqt-teal)_35%,transparent)] bg-[hsl(0_0%_0%/0.7)] px-3 py-1.5 text-caption text-[color:var(--aqt-teal)] backdrop-blur-sm"
        data-bracket-rearrange-hint
      >
        {t("bracket.rearrangeHint")}
      </p>
    ) : null;

  // Controls float over the canvas the way map controls do: bottom corners,
  // where no round header ever sits (the grand final's is top-right), and above
  // the scroller's own bar.
  const framed = (fullscreen: boolean) => (
    <div className={cn("relative", fullscreen && "flex min-h-0 flex-1 flex-col")}>
      {canvas(fullscreen)}
      <div className="pointer-events-none absolute inset-x-4 bottom-5 z-10 flex items-end justify-between gap-4">
        {rearrangeHint ?? <span />}
        <div className="pointer-events-auto">{toolbar(fullscreen)}</div>
      </div>
    </div>
  );

  return (
    <>
      <div className="overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]">
        {/* The inline frame keeps its footprint while the dialog holds the canvas,
            so closing fullscreen does not reflow the page under the viewer. */}
        {isFullscreen ? (
          <div className="max-h-[78vh]" style={{ height: layout.height * viewport.scale + 56 }} />
        ) : (
          framed(false)
        )}
      </div>

      {/* Radix owns the modal contract the hand-rolled overlay never had:
          role="dialog", aria-modal, a focus trap, focus restore on close and
          scroll locking. Escape came for free there; nothing else did. */}
      <Dialog open={isFullscreen} onOpenChange={setIsFullscreen}>
        {/* `max-h-screen`: a deliberate edge-to-edge surface, so it replaces the
            primitive's viewport height cap instead of sitting 2rem short of the
            bottom. (`max-h-none` would not: tailwind-merge v3 does not know that
            class, so both caps would survive into the class list.) */}
        <DialogContent className="left-0 top-0 flex h-screen max-h-screen w-screen max-w-none translate-x-0 translate-y-0 flex-col gap-0 overflow-hidden rounded-none border-none bg-[color:var(--aqt-bg)] p-6">
          <DialogHeader className="mb-4 flex-row items-start justify-between gap-4 space-y-0 border-b border-[color:var(--aqt-border)] pb-3 pr-12 text-left">
            <div>
              <DialogTitle className="text-xl font-bold uppercase tracking-wider text-[color:var(--aqt-fg)]">
                {bracketTitle}
              </DialogTitle>
              <DialogDescription className="text-xs text-[color:var(--aqt-fg-muted)]">
                {t("common.bracketInstructions")}
              </DialogDescription>
            </div>
          </DialogHeader>
          {isFullscreen ? framed(true) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
