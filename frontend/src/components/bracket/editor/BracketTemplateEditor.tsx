"use client";

import { useEffect, useMemo, useState } from "react";
import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent
} from "@dnd-kit/core";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { tint } from "@/lib/colors";
import { cn } from "@/lib/utils";
import type { StageType } from "@/types/tournament.types";

import { HEADER_CHIP } from "../BracketCanvas";
import { slotCollision, slotKeyboardCoordinates } from "../BracketView";
import { buildLayout, CARD_HEIGHT, CARD_WIDTH, PADDING_Y } from "../layout";
import { useBracketViewport } from "../useBracketViewport";
import { TemplateMatchCard, type ConnectSource, type TemplateSlotDrag } from "./TemplateMatchCard";
import { draftToBracketMatches, unusedSeeds, type Draft, type DraftAction } from "./templateDraft";

/** Room to the right of the tree for the two "+ round" buttons. */
const ADD_COLUMN_WIDTH = 132;

interface BracketTemplateEditorProps {
  draft: Draft;
  stageType: StageType;
  dispatch: (action: DraftAction) => void;
  highlightMatchId: number | null;
}

/**
 * The draft on the same canvas the bracket is drawn on everywhere else:
 * `buildLayout` for the geometry, `useBracketViewport` for pan and zoom, and
 * the generator's own slot hints ("W M3") read off the draft's edges.
 *
 * It composes those pieces rather than reusing `BracketCanvas`, which hard-wires
 * `MatchCard` — a viewer's card, with team links and scores. The cards here are
 * wiring boxes, and the loser drops are drawn (dashed) because the thing being
 * checked IS the wiring.
 */
export function BracketTemplateEditor({
  draft,
  stageType,
  dispatch,
  highlightMatchId
}: Readonly<BracketTemplateEditorProps>) {
  const t = useTranslations("bracketEditor");
  const roundLabel = useBracketRoundLabel({ bareUpper: true });
  const layout = useMemo(
    () =>
      buildLayout(draftToBracketMatches(draft), stageType, roundLabel, { includeLoserEdges: true }),
    [draft, stageType, roundLabel]
  );
  // Destructured, not held as one object: `attachScroller` is a ref callback,
  // and the lint rule reads any other field of the object it came from as a
  // ref access during render.
  const { scale, isGrabbing, attachScroller, scrollerHandlers } = useBracketViewport({
    layoutWidth: layout.width + ADD_COLUMN_WIDTH,
    focus: null
  });
  const [connecting, setConnecting] = useState<ConnectSource | null>(null);
  const [dragging, setDragging] = useState<TemplateSlotDrag | null>(null);
  const tDnd = useTranslations("bracket.dnd");
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: slotKeyboardCoordinates })
  );
  const onDragEnd = ({ active, over }: DragEndEvent) => {
    setDragging(null);
    const from = active.data.current as TemplateSlotDrag | undefined;
    const to = over?.data.current as TemplateSlotDrag | undefined;
    if (!from || !to || active.id === over?.id) return;
    dispatch({
      type: "swap",
      a: { match: from.match, slot: from.slot },
      b: { match: to.match, slot: to.slot }
    });
  };
  const labelOf = (data: unknown) => (data as TemplateSlotDrag).label;

  useEffect(() => {
    if (connecting === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConnecting(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [connecting]);

  // A match takes seeds from its own half only, so the two offers are built
  // once rather than per card.
  const upperSeeds = unusedSeeds(draft, 1);
  const lowerSeeds = unusedSeeds(draft, -1);
  const byId = new Map(draft.matches.map((match) => [match.id, match]));
  const isDE = stageType === "double_elimination";
  const rounds = draft.matches.map((match) => match.round);
  const upperRounds = rounds.filter((round) => round > 0);
  const lowerRounds = rounds.filter((round) => round < 0);
  // The last positive round holds the final, which is the one upper match that
  // drops nobody (`de_lower_loser`).
  const finalRound = upperRounds.length > 0 ? Math.max(...upperRounds) : 0;
  const lowerHeaderY = layout.headers.find((header) => header.section === "lower")?.y;

  const width = layout.width + ADD_COLUMN_WIDTH;

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={slotCollision}
      onDragStart={({ active }) =>
        setDragging((active.data.current as TemplateSlotDrag | undefined) ?? null)
      }
      onDragEnd={onDragEnd}
      onDragCancel={() => setDragging(null)}
      accessibility={{
        announcements: {
          onDragStart: ({ active }) => tDnd("pickedUp", { team: labelOf(active.data.current) }),
          onDragOver: ({ active, over }) =>
            over
              ? tDnd("over", {
                  team: labelOf(active.data.current),
                  slot: labelOf(over.data.current)
                })
              : tDnd("overNothing", { team: labelOf(active.data.current) }),
          onDragEnd: ({ active, over }) =>
            over
              ? tDnd("dropped", {
                  team: labelOf(active.data.current),
                  slot: labelOf(over.data.current)
                })
              : tDnd("cancelled", { team: labelOf(active.data.current) }),
          onDragCancel: ({ active }) => tDnd("cancelled", { team: labelOf(active.data.current) })
        },
        screenReaderInstructions: { draggable: tDnd("instructions") }
      }}
    >
      <div
        ref={attachScroller}
        className={cn(
          "max-h-[70vh] select-none overflow-auto rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]",
          isGrabbing ? "cursor-grabbing" : "cursor-grab"
        )}
        {...scrollerHandlers}
      >
        <div
          className="relative min-w-full"
          style={{ width: width * scale, height: layout.height * scale }}
        >
          <div
            className="relative origin-top-left"
            style={{
              width,
              height: layout.height,
              transform: scale === 1 ? undefined : `scale(${scale})`,
              backgroundImage:
                "radial-gradient(circle at 1px 1px, hsl(0 0% 100% / 0.05) 1px, transparent 0)",
              backgroundSize: "22px 22px"
            }}
          >
            <svg
              className="pointer-events-none absolute inset-0"
              width={width}
              height={layout.height}
              viewBox={`0 0 ${width} ${layout.height}`}
              fill="none"
              aria-hidden
            >
              {layout.edges.map((edge) => (
                <path
                  key={edge.id}
                  data-edge={edge.id}
                  data-edge-kind={edge.kind}
                  d={edge.path}
                  stroke={
                    edge.kind === "loser" ? tint("var(--aqt-blue)", 70) : "hsl(0 0% 100% / 0.22)"
                  }
                  strokeWidth={2}
                  strokeDasharray={edge.kind === "loser" ? "5 4" : undefined}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              ))}
            </svg>

            {layout.headers.map((header) => (
              <div
                key={header.id}
                className="absolute flex items-center gap-1.5"
                style={{ left: header.x, top: header.y, width: CARD_WIDTH }}
              >
                <span className={cn(HEADER_CHIP, "gap-2")}>
                  <span
                    aria-hidden
                    className="h-2 w-2 rounded-full"
                    style={{
                      background: header.section === "upper" ? "var(--aqt-teal)" : "var(--aqt-blue)"
                    }}
                  />
                  {header.label}
                </span>
                <Button
                  type="button"
                  variant="dashed"
                  size="xs"
                  aria-label={t("addMatchTo", { label: header.label })}
                  data-add-match={header.round}
                  onClick={() => dispatch({ type: "addMatch", round: header.round })}
                >
                  <Plus aria-hidden />
                  {t("match")}
                </Button>
              </div>
            ))}

            {/* "+ round" at the end of each section. On the upper one it inserts
              BEFORE the final, which is by definition the last positive round. */}
            <div className="absolute" style={{ left: layout.width, top: PADDING_Y }}>
              <Button
                type="button"
                variant="dashed"
                size="xs"
                aria-label={t("addUpperRound")}
                onClick={() =>
                  dispatch(
                    finalRound > 0
                      ? { type: "addMatch", round: finalRound, beforeFinal: true }
                      : { type: "addMatch", round: 1 }
                  )
                }
              >
                <Plus aria-hidden />
                {t("upperRound")}
              </Button>
            </div>
            {isDE ? (
              <div
                className="absolute"
                style={{ left: layout.width, top: lowerHeaderY ?? PADDING_Y + 28 }}
              >
                <Button
                  type="button"
                  variant="dashed"
                  size="xs"
                  aria-label={t("addLowerRound")}
                  onClick={() =>
                    dispatch({
                      type: "addMatch",
                      round: lowerRounds.length > 0 ? Math.min(...lowerRounds) - 1 : -1
                    })
                  }
                >
                  <Plus aria-hidden />
                  {t("lowerRound")}
                </Button>
              </div>
            ) : null}

            {layout.nodes.map((node) => {
              const match = byId.get(node.encounter.id);
              if (!match) return null;
              const highlighted = highlightMatchId === match.id;
              return (
                <div
                  key={node.id}
                  data-match-id={match.id}
                  data-highlighted={highlighted || undefined}
                  className={cn(
                    "absolute rounded-[10px]",
                    highlighted &&
                      "ring-2 ring-[color:var(--aqt-amber)] ring-offset-2 ring-offset-[color:var(--aqt-bg-2)]"
                  )}
                  style={{ left: node.x, top: node.y, width: CARD_WIDTH, height: CARD_HEIGHT }}
                >
                  <TemplateMatchCard
                    match={match}
                    availableSeeds={match.round < 0 ? lowerSeeds : upperSeeds}
                    showLoserPort={isDE && match.round > 0 && match.round !== finalRound}
                    connecting={connecting}
                    onPort={(role) =>
                      setConnecting((current) =>
                        current?.source === match.id && current.role === role
                          ? null
                          : { source: match.id, role }
                      )
                    }
                    onConnect={(slot) => {
                      if (!connecting) return;
                      dispatch({ type: "connect", ...connecting, target: match.id, slot });
                      setConnecting(null);
                    }}
                    onSeed={(slot, seed) =>
                      dispatch({ type: "seed", target: match.id, slot, seed })
                    }
                    onClear={(slot) => dispatch({ type: "clear", target: match.id, slot })}
                    onMove={(direction) => dispatch({ type: "move", id: match.id, direction })}
                    onDelete={() => dispatch({ type: "deleteMatch", id: match.id })}
                  />
                </div>
              );
            })}
          </div>
        </div>
      </div>
      <DragOverlay dropAnimation={null}>
        {dragging ? (
          <div className="rounded-md border border-[color:var(--aqt-teal)] bg-[color:var(--aqt-card)] px-2.5 py-1 text-caption font-semibold text-[color:var(--aqt-fg)] shadow-[0_10px_24px_rgba(0,0,0,0.4)]">
            {dragging.label}
          </div>
        ) : null}
      </DragOverlay>
    </DndContext>
  );
}
