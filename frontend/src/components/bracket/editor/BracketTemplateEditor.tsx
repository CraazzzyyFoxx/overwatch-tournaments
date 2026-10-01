"use client";

import { useEffect, useMemo, useState } from "react";
import { Plus } from "lucide-react";

import { useBracketRoundLabel } from "@/hooks/useBracketRoundLabel";
import { cn } from "@/lib/utils";
import type { StageType } from "@/types/tournament.types";

import { buildLayout, CARD_HEIGHT, CARD_WIDTH, PADDING_Y } from "../layout";
import { useBracketViewport } from "../useBracketViewport";
import { TemplateMatchCard, type ConnectSource } from "./TemplateMatchCard";
import {
  draftToBracketMatches,
  unusedSeeds,
  type Draft,
  type DraftAction
} from "./templateDraft";

/** Room to the right of the tree for the two "+ round" buttons. */
const ADD_COLUMN_WIDTH = 132;

const ADD_BUTTON =
  "inline-flex items-center gap-1 rounded-full border border-dashed border-[color:var(--aqt-border-2)] px-2 py-0.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)] transition-colors hover:border-[color:var(--aqt-teal)] hover:text-[color:var(--aqt-teal)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]";

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
  const roundLabel = useBracketRoundLabel({ bareUpper: true });
  const layout = useMemo(
    () => buildLayout(draftToBracketMatches(draft), stageType, roundLabel, { includeLoserEdges: true }),
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

  useEffect(() => {
    if (connecting === null) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setConnecting(null);
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [connecting]);

  const seeds = unusedSeeds(draft);
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
                  edge.kind === "loser" ? "color-mix(in srgb, var(--aqt-blue) 70%, transparent)" : "hsl(0 0% 100% / 0.22)"
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
              <span className="inline-flex items-center gap-2 rounded-full border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_0%/0.55)] px-2.5 py-0.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
                <span
                  aria-hidden
                  className="h-2 w-2 rounded-full"
                  style={{ background: header.section === "upper" ? "var(--aqt-teal)" : "var(--aqt-blue)" }}
                />
                {header.label}
              </span>
              <button
                type="button"
                aria-label={`Add match to ${header.label}`}
                data-add-match={header.round}
                className={ADD_BUTTON}
                onClick={() => dispatch({ type: "addMatch", round: header.round })}
              >
                <Plus className="size-3" aria-hidden />
                match
              </button>
            </div>
          ))}

          {/* "+ round" at the end of each section. On the upper one it inserts
              BEFORE the final, which is by definition the last positive round. */}
          <div className="absolute" style={{ left: layout.width, top: PADDING_Y }}>
            <button
              type="button"
              aria-label="Add upper round"
              className={cn(ADD_BUTTON, "whitespace-nowrap")}
              onClick={() =>
                dispatch(
                  finalRound > 0
                    ? { type: "addMatch", round: finalRound, beforeFinal: true }
                    : { type: "addMatch", round: 1 }
                )
              }
            >
              <Plus className="size-3" aria-hidden />
              upper round
            </button>
          </div>
          {isDE ? (
            <div
              className="absolute"
              style={{ left: layout.width, top: lowerHeaderY ?? PADDING_Y + 28 }}
            >
              <button
                type="button"
                aria-label="Add lower round"
                className={cn(ADD_BUTTON, "whitespace-nowrap")}
                onClick={() =>
                  dispatch({
                    type: "addMatch",
                    round: lowerRounds.length > 0 ? Math.min(...lowerRounds) - 1 : -1
                  })
                }
              >
                <Plus className="size-3" aria-hidden />
                lower round
              </button>
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
                  availableSeeds={seeds}
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
                  onSeed={(slot, seed) => dispatch({ type: "seed", target: match.id, slot, seed })}
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
  );
}
