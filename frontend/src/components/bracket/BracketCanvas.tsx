"use client";

import { useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { isSlotRearrangeable, type BracketMatch } from "@/lib/bracket/view";
import { cn } from "@/lib/utils";
import type { StreamEntry } from "@/types/stream.types";

import { MatchCard } from "./MatchCard";
import { CARD_HEIGHT, CARD_WIDTH, PADDING_Y, type BracketLayout, type LayoutHeader } from "./layout";
import type { BracketViewport } from "./useBracketViewport";

interface BracketCanvasProps extends Pick<BracketViewport, "scale" | "isGrabbing" | "attachScroller" | "scrollerHandlers"> {
  layout: BracketLayout;
  fullscreen: boolean;
  hoveredTeamId: number | null;
  onHoverTeam: (teamId: number | null) => void;
  returnTo: string;
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  interactive: boolean;
  highlightMatchId: number | null;
  rearranging: boolean;
  /** Footer controls for one card (edit, report); `null` for none. */
  renderActions: (encounter: BracketMatch) => ReactNode;
}

function RoundHeader({ header, scale, sticky }: Readonly<{ header: LayoutHeader; scale: number; sticky: boolean }>) {
  return (
    <div
      data-round-header={header.id}
      className="absolute"
      style={
        sticky
          ? { left: header.x * scale, top: header.y * scale, width: CARD_WIDTH * scale }
          : { left: header.x, top: header.y, width: CARD_WIDTH }
      }
    >
      <div className="inline-flex items-center gap-2 rounded-full border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_0%/0.55)] px-2.5 py-0.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)] backdrop-blur-sm">
        <span
          aria-hidden
          className="h-2 w-2 rounded-full"
          style={{ background: header.section === "upper" ? "var(--aqt-teal)" : "var(--aqt-blue)" }}
        />
        <span>{header.label}</span>
      </div>
    </div>
  );
}

/**
 * The scrolling, zooming surface: connectors, round headers and one `MatchCard`
 * per node at the coordinates `buildLayout` gave them.
 *
 * One instance at a time — inline or in the fullscreen dialog — so the deep-link
 * scroll and the opening-round focus each fire once, and a 63-card tree is not
 * mounted twice while a viewer looks at one copy.
 */
export function BracketCanvas({
  layout,
  scale,
  isGrabbing,
  attachScroller,
  scrollerHandlers,
  fullscreen,
  hoveredTeamId,
  onHoverTeam,
  returnTo,
  liveTeamStreams,
  interactive,
  highlightMatchId,
  rearranging,
  renderActions
}: Readonly<BracketCanvasProps>) {
  const t = useTranslations();
  // Deep link: bring the node into view once per mount, not on every re-render
  // (a hover or a poll landing must not re-centre a viewer who panned away).
  const scrolledTo = useRef<number | null>(null);
  const highlightedRef = (el: HTMLDivElement | null) => {
    if (!el || scrolledTo.current === highlightMatchId) return;
    scrolledTo.current = highlightMatchId;
    el.scrollIntoView({ block: "center", inline: "center" });
  };
  const rootRef = useRef<HTMLDivElement>(null);

  // Roving tabindex over the cards: one stop for the whole tree, arrows walk
  // it along the connectors (←/→) and down a column (↑/↓).
  const [focusedId, setFocusedId] = useState<number | null>(
    () => highlightMatchId ?? layout.nodes[0]?.encounter.id ?? null
  );
  const neighbours = useMemo(() => {
    const next = new Map<number, number>();
    const prev = new Map<number, number>();
    for (const edge of layout.edges) {
      if (!next.has(edge.sourceId)) next.set(edge.sourceId, edge.targetId);
      if (!prev.has(edge.targetId)) prev.set(edge.targetId, edge.sourceId);
    }
    const byColumn = new Map<number, number[]>();
    for (const node of [...layout.nodes].sort((a, b) => a.y - b.y)) {
      const column = byColumn.get(node.x) ?? [];
      column.push(node.encounter.id);
      byColumn.set(node.x, column);
    }
    const up = new Map<number, number>();
    const down = new Map<number, number>();
    for (const column of byColumn.values()) {
      column.forEach((id, index) => {
        if (index > 0) up.set(id, column[index - 1]);
        if (index < column.length - 1) down.set(id, column[index + 1]);
      });
    }
    return { next, prev, up, down };
  }, [layout.edges, layout.nodes]);

  const focusCard = (id: number | undefined) => {
    if (id === undefined) return;
    rootRef.current?.querySelector<HTMLElement>(`[data-match-id="${id}"]`)?.focus();
  };
  const onCardKeyDown = (event: KeyboardEvent<HTMLDivElement>, id: number) => {
    if (event.target !== event.currentTarget) return;
    const step = {
      ArrowRight: neighbours.next,
      ArrowLeft: neighbours.prev,
      ArrowUp: neighbours.up,
      ArrowDown: neighbours.down
    }[event.key];
    if (!step) return;
    event.preventDefault();
    focusCard(step.get(id));
  };

  // The upper row of headers pins to the top while the tree scrolls under it;
  // the lower bracket's headers label a section mid-canvas and stay put.
  const stickyHeaders = layout.headers.filter((header) => header.y === PADDING_Y);
  const canvasHeaders = layout.headers.filter((header) => header.y !== PADDING_Y);

  return (
    <div
      ref={attachScroller}
      className={cn(
        // Bottom padding is the floating toolbar's lane: the last row of cards
        // can always scroll clear of it.
        "select-none overflow-auto pb-14",
        fullscreen ? "h-full w-full flex-1" : "max-h-[78vh]",
        isGrabbing ? "cursor-grabbing" : "cursor-grab"
      )}
      {...scrollerHandlers}
    >
      <div
        className="pointer-events-none sticky top-0 z-[2] h-0"
        style={{ width: layout.width * scale }}
      >
        {stickyHeaders.map((header) => (
          <RoundHeader key={header.id} header={header} scale={scale} sticky />
        ))}
      </div>
      <div
        className="relative min-w-full"
        style={{ width: layout.width * scale, height: layout.height * scale }}
      >
        <div
          ref={rootRef}
          className="relative origin-top-left"
          style={{
            width: layout.width,
            height: layout.height,
            transform: scale === 1 ? undefined : `scale(${scale})`,
            backgroundImage: "radial-gradient(circle at 1px 1px, hsl(0 0% 100% / 0.05) 1px, transparent 0)",
            backgroundSize: "22px 22px"
          }}
        >
          <svg
            className="pointer-events-none absolute inset-0"
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            fill="none"
            aria-hidden
          >
            {layout.edges.map((edge) => {
              const onPath = hoveredTeamId !== null && edge.teamId === hoveredTeamId;
              return (
                <path
                  key={edge.id}
                  data-edge={edge.id}
                  data-edge-team={edge.teamId ?? undefined}
                  d={edge.path}
                  stroke={
                    onPath
                      ? "var(--aqt-teal)"
                      : edge.isCompleted
                        ? "color-mix(in srgb, var(--aqt-teal) 55%, transparent)"
                        : "hsl(0 0% 100% / 0.12)"
                  }
                  strokeWidth={onPath ? 3 : 2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              );
            })}
          </svg>

          {canvasHeaders.map((header) => (
            <RoundHeader key={header.id} header={header} scale={scale} sticky={false} />
          ))}

          {layout.nodes.map((node) => {
            const match = node.encounter;
            const highlighted = highlightMatchId !== null && match.id === highlightMatchId;
            return (
              <div
                key={node.id}
                ref={highlighted ? highlightedRef : undefined}
                data-match-id={match.id}
                role="group"
                aria-label={t("bracket.matchAria", {
                  label: node.data.matchLabel,
                  home: node.data.homeName === "TBD" ? t("common.tbd") : node.data.homeName,
                  away: node.data.awayName === "TBD" ? t("common.tbd") : node.data.awayName
                })}
                tabIndex={match.id === focusedId ? 0 : -1}
                onFocus={() => setFocusedId(match.id)}
                onKeyDown={(event) => onCardKeyDown(event, match.id)}
                className={cn(
                  "absolute rounded-[10px] outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-blue)] focus-visible:ring-offset-2 focus-visible:ring-offset-[color:var(--aqt-bg-2)]",
                  highlighted &&
                    "ring-2 ring-[color:var(--aqt-teal)] ring-offset-2 ring-offset-[color:var(--aqt-card)]"
                )}
                style={{ left: node.x, top: node.y, width: CARD_WIDTH, height: CARD_HEIGHT }}
              >
                <MatchCard
                  node={node}
                  homeHighlighted={node.data.homeTeamId !== null && node.data.homeTeamId === hoveredTeamId}
                  awayHighlighted={node.data.awayTeamId !== null && node.data.awayTeamId === hoveredTeamId}
                  onHoverTeam={onHoverTeam}
                  returnTo={returnTo}
                  liveTeamStreams={liveTeamStreams}
                  interactive={interactive}
                  rearranging={rearranging}
                  draggable={rearranging && isSlotRearrangeable(match)}
                  renderActions={renderActions}
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
