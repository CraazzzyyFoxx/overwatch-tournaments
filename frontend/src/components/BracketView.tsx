"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Pencil, FileEdit, Maximize2, Minimize2 } from "lucide-react";

import { cn } from "@/lib/utils";
import { useTranslation } from "@/i18n/LanguageContext";
import type { Encounter } from "@/types/encounter.types";
import type { StageType } from "@/types/tournament.types";
import {
  buildRoundGroups as buildBracketRoundGroups,
  computeMatchNumbers as computeBracketMatchNumbers,
  computeSlotHints as computeBracketSlotHints,
  getDoubleEliminationFinalRounds as getBracketFinalRounds,
  getGrandFinalLabel as getBracketGrandFinalLabel,
  getRoundSectionMatchCapacity
} from "@/components/bracket-view.helpers";

interface BracketViewProps {
  encounters: Encounter[];
  type: StageType;
  onEdit?: (encounter: Encounter) => void;
  onReport?: (encounter: Encounter) => void;
  canEdit?: (encounter: Encounter) => boolean;
  canReport?: (encounter: Encounter) => boolean;
}

interface MatchNodeData {
  matchLabel: string;
  homeName: string;
  awayName: string;
  homeSource: string | null;
  awaySource: string | null;
  homeTeamId: number | null;
  awayTeamId: number | null;
  homeScore: number;
  awayScore: number;
  winner: "home" | "away" | null;
  isCompleted: boolean;
}

interface LayoutNode {
  id: string;
  x: number;
  y: number;
  data: MatchNodeData;
  encounter: Encounter;
}

interface LayoutEdge {
  id: string;
  path: string;
  isCompleted: boolean;
}

interface LayoutHeader {
  id: string;
  x: number;
  y: number;
  label: string;
  section: "upper" | "lower";
}

interface RoundGroup {
  round: number;
  matches: Encounter[];
}

interface BracketLayout {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  headers: LayoutHeader[];
  width: number;
  height: number;
}

const CARD_WIDTH = 210;
const CARD_HEIGHT = 84;
const CARD_ROW_HEIGHT = 30;
const ROUND_GAP_X = 48;
const MATCH_GAP_Y = 10;
const HEADER_HEIGHT = 24;
const SECTION_GAP_Y = 52;
const PADDING_X = 16;
const PADDING_Y = 14;
const BADGE_RIGHT = 44;

const COMPLETED_STATUSES = new Set(["completed", "finished", "closed"]);
const NAME_SEPARATORS = [" vs. ", " vs ", " VS ", " - ", " v "];

function splitEncounterName(name: string | null | undefined) {
  const value = name?.trim();

  if (!value) {
    return { homeName: null, awayName: null };
  }

  for (const separator of NAME_SEPARATORS) {
    if (!value.includes(separator)) {
      continue;
    }

    const [homeName, awayName] = value.split(separator, 2).map((part) => part.trim());

    if (homeName && awayName) {
      return { homeName, awayName };
    }
  }

  return { homeName: null, awayName: null };
}

function getMatchNames(match: Encounter) {
  const parsed = splitEncounterName(match.name);

  return {
    homeName: match.home_team?.name?.trim() || parsed.homeName || "TBD",
    awayName: match.away_team?.name?.trim() || parsed.awayName || "TBD"
  };
}

function getWinner(match: Encounter): "home" | "away" | null {
  if (!COMPLETED_STATUSES.has(match.status)) {
    return null;
  }

  if (match.score.home === match.score.away) {
    return null;
  }

  return match.score.home > match.score.away ? "home" : "away";
}

function buildPath(source: LayoutNode, target: LayoutNode) {
  const startX = source.x + CARD_WIDTH;
  const startY = source.y + CARD_HEIGHT / 2;
  const endX = target.x;
  const endY = target.y + CARD_HEIGHT / 2;
  const middleX = startX + ROUND_GAP_X / 2;

  return `M ${startX} ${startY} H ${middleX} V ${endY} H ${endX}`;
}

function createNode(
  match: Encounter,
  x: number,
  y: number,
  matchNumber: number,
  homeSource: string | null,
  awaySource: string | null
): LayoutNode {
  const names = getMatchNames(match);

  return {
    id: `match-${match.id}`,
    x,
    y,
    data: {
      matchLabel: `M${matchNumber}`,
      homeName: names.homeName,
      awayName: names.awayName,
      homeSource: names.homeName === "TBD" ? homeSource : null,
      awaySource: names.awayName === "TBD" ? awaySource : null,
      homeTeamId: match.home_team_id > 0 ? match.home_team_id : null,
      awayTeamId: match.away_team_id > 0 ? match.away_team_id : null,
      homeScore: match.score.home,
      awayScore: match.score.away,
      winner: getWinner(match),
      isCompleted: COMPLETED_STATUSES.has(match.status)
    },
    encounter: match
  };
}

function addSequentialEdges(
  groups: RoundGroup[],
  nodesById: Map<string, LayoutNode>,
  edges: LayoutEdge[],
  mapper: (matchIndex: number, targetCount: number) => number
) {
  for (let groupIndex = 0; groupIndex < groups.length - 1; groupIndex++) {
    const current = groups[groupIndex].matches;
    const next = groups[groupIndex + 1].matches;

    for (let matchIndex = 0; matchIndex < current.length; matchIndex++) {
      const targetIndex = mapper(matchIndex, next.length);

      if (targetIndex < 0 || targetIndex >= next.length) {
        continue;
      }

      const sourceNode = nodesById.get(`match-${current[matchIndex].id}`);
      const targetNode = nodesById.get(`match-${next[targetIndex].id}`);

      if (!sourceNode || !targetNode) {
        continue;
      }

      edges.push({
        id: `edge-${current[matchIndex].id}-${next[targetIndex].id}`,
        path: buildPath(sourceNode, targetNode),
        isCompleted: COMPLETED_STATUSES.has(current[matchIndex].status)
      });
    }
  }
}

function buildLayout(encounters: Encounter[], type: StageType): BracketLayout {
  const hasBracketConnections = type === "single_elimination" || type === "double_elimination";

  const isDE = type === "double_elimination";
  const finalRoundNumbers = isDE ? getBracketFinalRounds(encounters) : new Set<number>();

  // For DE: split upper encounters into regular UB and Grand Final section.
  const ubEncounters = isDE
    ? encounters.filter((match) => match.round > 0 && !finalRoundNumbers.has(match.round))
    : encounters.filter((m) => m.round > 0);
  const finalEncounters = isDE
    ? encounters.filter((match) => match.round > 0 && finalRoundNumbers.has(match.round))
    : [];

  const upperRounds = buildBracketRoundGroups(ubEncounters);
  const finalRounds = buildBracketRoundGroups(finalEncounters);
  const lowerRounds = isDE
    ? buildBracketRoundGroups(encounters.filter((match) => match.round < 0))
    : [];

  // Main bracket columns (UB and LB); finals go in extra columns at the right.
  const mainColumns = Math.max(upperRounds.length, lowerRounds.length, 1);
  const totalColumns = mainColumns + finalRounds.length;
  const contentWidth = totalColumns * CARD_WIDTH + Math.max(totalColumns - 1, 0) * ROUND_GAP_X;
  const width = PADDING_X * 2 + contentWidth + BADGE_RIGHT;

  const nodes: LayoutNode[] = [];
  const edges: LayoutEdge[] = [];
  const headers: LayoutHeader[] = [];

  const matchNumbers = computeBracketMatchNumbers(upperRounds, lowerRounds, finalRounds);
  const slotHints = computeBracketSlotHints(
    upperRounds,
    lowerRounds,
    finalRounds,
    matchNumbers,
    isDE,
    hasBracketConnections
  );

  const upperBaseMatches = getRoundSectionMatchCapacity(upperRounds);
  const upperBasePitch = CARD_HEIGHT + MATCH_GAP_Y;
  const upperSectionHeight = Math.max(
    upperBaseMatches * CARD_HEIGHT + Math.max(upperBaseMatches - 1, 0) * MATCH_GAP_Y,
    CARD_HEIGHT
  );
  const widestUpperRoundIndex = Math.max(
    0,
    upperRounds.findIndex((group) => group.matches.length === upperBaseMatches)
  );
  const upperStartX = PADDING_X;
  const upperHeaderY = PADDING_Y;
  const upperTop = upperHeaderY + HEADER_HEIGHT;

  upperRounds.forEach((group, columnIndex) => {
    const x = upperStartX + columnIndex * (CARD_WIDTH + ROUND_GAP_X);
    const totalHeight =
      group.matches.length * CARD_HEIGHT + Math.max(group.matches.length - 1, 0) * MATCH_GAP_Y;
    const isSparsePlayInRound =
      columnIndex < widestUpperRoundIndex && group.matches.length < upperBaseMatches;
    const startY =
      upperTop +
      (isSparsePlayInRound
        ? upperBasePitch / 2
        : Math.max(0, (upperSectionHeight - totalHeight) / 2));

    headers.push({
      id: `upper-header-${group.round}`,
      x,
      y: upperHeaderY,
      label: `Round ${group.round}`,
      section: "upper"
    });

    group.matches.forEach((match, matchIndex) => {
      const hint = slotHints.get(match.id) ?? { home: null, away: null };
      const n = matchNumbers.get(match.id) ?? 0;
      nodes.push(
        createNode(match, x, startY + matchIndex * upperBasePitch, n, hint.home, hint.away)
      );
    });
  });

  const hasLowerBracket = lowerRounds.length > 0;
  const lowerHeaderY = upperTop + upperSectionHeight + (hasLowerBracket ? SECTION_GAP_Y : 0);
  const lowerTop = lowerHeaderY + HEADER_HEIGHT;
  const maxLowerMatches = Math.max(1, ...lowerRounds.map((group) => group.matches.length));
  const lowerSectionHeight = hasLowerBracket
    ? Math.max(
        maxLowerMatches * CARD_HEIGHT + Math.max(maxLowerMatches - 1, 0) * MATCH_GAP_Y,
        CARD_HEIGHT
      )
    : 0;
  const lowerStartX = PADDING_X;

  lowerRounds.forEach((group, columnIndex) => {
    const x = lowerStartX + columnIndex * (CARD_WIDTH + ROUND_GAP_X);
    const totalHeight =
      group.matches.length * CARD_HEIGHT + Math.max(group.matches.length - 1, 0) * MATCH_GAP_Y;
    const startY = lowerTop + Math.max(0, (lowerSectionHeight - totalHeight) / 2);

    headers.push({
      id: `lower-header-${group.round}`,
      x,
      y: lowerHeaderY,
      label: `Lower R${Math.abs(group.round)}`,
      section: "lower"
    });

    group.matches.forEach((match, matchIndex) => {
      const hint = slotHints.get(match.id) ?? { home: null, away: null };
      const n = matchNumbers.get(match.id) ?? 0;
      nodes.push(
        createNode(
          match,
          x,
          startY + matchIndex * (CARD_HEIGHT + MATCH_GAP_Y),
          n,
          hint.home,
          hint.away
        )
      );
    });
  });

  // Grand Final section: placed right of both UB and LB, vertically centered
  // in the full bracket height.
  const fullContentHeight = hasLowerBracket
    ? lowerTop + lowerSectionHeight
    : upperTop + upperSectionHeight;

  finalRounds.forEach((group, finalIndex) => {
    const columnIndex = mainColumns + finalIndex;
    const x = PADDING_X + columnIndex * (CARD_WIDTH + ROUND_GAP_X);
    const totalHeight =
      group.matches.length * CARD_HEIGHT + Math.max(group.matches.length - 1, 0) * MATCH_GAP_Y;
    const startY = Math.max(0, (fullContentHeight - totalHeight) / 2);

    headers.push({
      id: `final-header-${group.round}`,
      x,
      y: PADDING_Y,
      label: getBracketGrandFinalLabel(group.round, finalRounds),
      section: "upper"
    });

    group.matches.forEach((match, matchIndex) => {
      const hint = slotHints.get(match.id) ?? { home: null, away: null };
      const n = matchNumbers.get(match.id) ?? 0;
      nodes.push(
        createNode(
          match,
          x,
          startY + matchIndex * (CARD_HEIGHT + MATCH_GAP_Y),
          n,
          hint.home,
          hint.away
        )
      );
    });
  });

  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  if (hasBracketConnections) {
    // UB sequential edges (excludes GF since finalRounds is separate).
    addSequentialEdges(upperRounds, nodesById, edges, (matchIndex, targetCount) => {
      const targetIndex = Math.floor(matchIndex / 2);
      return targetIndex < targetCount ? targetIndex : -1;
    });

    addSequentialEdges(lowerRounds, nodesById, edges, (matchIndex, targetCount) => {
      if (targetCount === 0) return -1;
      return Math.min(matchIndex, targetCount - 1);
    });
  }

  // For DE: draw UB Final → GF and LB Final → GF edges explicitly.
  if (isDE && finalRounds.length > 0) {
    const gfGroup = finalRounds[0];
    const gfMatch = gfGroup?.matches[0];
    const gfNode = gfMatch ? nodesById.get(`match-${gfMatch.id}`) : undefined;

    if (gfNode) {
      const ubFinalGroup = upperRounds[upperRounds.length - 1];
      const ubFinalMatch = ubFinalGroup?.matches[0];
      const ubFinalNode = ubFinalMatch ? nodesById.get(`match-${ubFinalMatch.id}`) : undefined;
      if (ubFinalNode) {
        edges.push({
          id: `edge-ub-final-gf`,
          path: buildPath(ubFinalNode, gfNode),
          isCompleted: COMPLETED_STATUSES.has(ubFinalMatch!.status)
        });
      }

      const lbFinalGroup = lowerRounds[lowerRounds.length - 1];
      const lbFinalMatch = lbFinalGroup?.matches[0];
      const lbFinalNode = lbFinalMatch ? nodesById.get(`match-${lbFinalMatch.id}`) : undefined;
      if (lbFinalNode) {
        edges.push({
          id: `edge-lb-final-gf`,
          path: buildPath(lbFinalNode, gfNode),
          isCompleted: COMPLETED_STATUSES.has(lbFinalMatch!.status)
        });
      }
    }

    // GF → GF Reset edge (if reset match exists).
    if (finalRounds.length > 1) {
      const gfrGroup = finalRounds[1];
      const gfrMatch = gfrGroup?.matches[0];
      const gfrNode = gfrMatch ? nodesById.get(`match-${gfrMatch.id}`) : undefined;
      if (gfNode && gfrNode) {
        edges.push({
          id: `edge-gf-gfr`,
          path: buildPath(gfNode, gfrNode),
          isCompleted: COMPLETED_STATUSES.has(gfMatch!.status)
        });
      }
    }
  }

  const height = hasLowerBracket
    ? lowerTop + lowerSectionHeight + PADDING_Y
    : upperTop + upperSectionHeight + PADDING_Y;

  return {
    nodes,
    edges,
    headers,
    width,
    height
  };
}

function getMatchMeta(encounter: Encounter) {
  const isCompleted = COMPLETED_STATUSES.has(encounter.status);
  const isLive = !isCompleted && Boolean(encounter.started_at) && !encounter.ended_at;
  const played = (encounter.score?.home ?? 0) + (encounter.score?.away ?? 0);
  const bestOf = encounter.best_of ?? 0;

  let timeLabel = "TBD";
  if (isCompleted) timeLabel = "Final";
  else if (isLive) timeLabel = "Live";
  else if (encounter.scheduled_at) {
    timeLabel = new Date(encounter.scheduled_at).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric"
    });
  }

  return { isCompleted, isLive, played, bestOf, timeLabel };
}

function MatchCard({
  data,
  encounter,
  hoveredTeamId,
  onHoveredTeamChange
}: {
  data: MatchNodeData;
  encounter: Encounter;
  hoveredTeamId: number | null;
  onHoveredTeamChange: (teamId: number | null) => void;
}) {
  const meta = getMatchMeta(encounter);
  const hasVisibleScore = data.isCompleted || data.homeScore !== 0 || data.awayScore !== 0;
  const footerHeight = CARD_HEIGHT - CARD_ROW_HEIGHT * 2;

  const getRowClasses = (side: "home" | "away") => {
    if (data.winner === side) {
      return "bg-[hsl(174_72%_46%/0.10)] text-[var(--aqt-fg)] font-semibold";
    }
    if (data.winner && data.winner !== side) {
      return "text-[var(--aqt-fg-dim)]";
    }
    return "text-[var(--aqt-fg-muted)]";
  };

  const getTeamId = (side: "home" | "away") =>
    side === "home" ? data.homeTeamId : data.awayTeamId;

  const isHighlighted = (side: "home" | "away") => {
    const teamId = getTeamId(side);
    return teamId != null && hoveredTeamId === teamId;
  };

  const handlePointerEnter = (side: "home" | "away") => onHoveredTeamChange(getTeamId(side));
  const handlePointerLeave = (side: "home" | "away") => {
    if (isHighlighted(side)) onHoveredTeamChange(null);
  };

  const getDisplayName = (side: "home" | "away") => {
    const name = side === "home" ? data.homeName : data.awayName;
    if (name === "TBD") {
      const source = side === "home" ? data.homeSource : data.awaySource;
      return source ?? "TBD";
    }
    return name;
  };

  const isTbdSlot = (side: "home" | "away") =>
    (side === "home" ? data.homeName : data.awayName) === "TBD";

  const renderRow = (side: "home" | "away") => {
    const score = side === "home" ? data.homeScore : data.awayScore;
    const won = data.winner === side;
    return (
      <div
        className={cn(
          "flex items-center justify-between gap-2 px-2.5 transition-colors",
          side === "home" && "border-b border-[var(--aqt-border)]",
          getRowClasses(side),
          isHighlighted(side) && "bg-[hsl(174_72%_46%/0.16)] text-[var(--aqt-fg)]"
        )}
        data-team-id={getTeamId(side) ?? undefined}
        data-team-highlighted={isHighlighted(side) || undefined}
        onPointerEnter={() => handlePointerEnter(side)}
        onPointerLeave={() => handlePointerLeave(side)}
        style={{ height: CARD_ROW_HEIGHT }}
      >
        <span
          className={cn(
            "min-w-0 truncate",
            isTbdSlot(side) ? "text-[11px] italic text-[var(--aqt-fg-faint)]" : "text-[12.5px]"
          )}
        >
          {getDisplayName(side)}
        </span>
        <span
          className={cn(
            "shrink-0 text-[13px] font-semibold tabular-nums",
            won ? "text-[var(--aqt-teal)]" : "text-[var(--aqt-fg-muted)]"
          )}
        >
          {hasVisibleScore ? score : "-"}
        </span>
      </div>
    );
  };

  return (
    <div
      className={cn(
        "relative flex h-full flex-col overflow-hidden rounded-[10px] border bg-[var(--aqt-card)] shadow-[0_10px_24px_rgba(0,0,0,0.28)]",
        meta.isLive
          ? "border-[hsl(340_75%_58%/0.45)]"
          : data.winner
            ? "border-[var(--aqt-border-2)]"
            : "border-[var(--aqt-border)]"
      )}
    >
      {renderRow("home")}
      {renderRow("away")}

      <div
        className="flex items-center justify-between gap-2 border-t border-[var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-2.5"
        style={{ height: footerHeight }}
      >
        <div className="flex items-center gap-2">
          {meta.bestOf > 0 && (
            <span className="font-mono text-[10px] font-semibold text-[var(--aqt-fg-faint)]">
              BO{meta.bestOf}
            </span>
          )}
          {meta.bestOf > 0 && (
            <span className="flex items-center gap-[3px]">
              {Array.from({ length: meta.bestOf }).map((_, index) => (
                <span
                  key={index}
                  className="h-1.5 w-1.5 rounded-full"
                  style={{
                    background:
                      index < meta.played ? "var(--aqt-teal)" : "hsl(0 0% 100% / 0.12)"
                  }}
                />
              ))}
            </span>
          )}
        </div>
        <span
          className={cn(
            "flex items-center gap-1 font-mono text-[10px] font-semibold uppercase tracking-wide",
            meta.isLive
              ? "text-[var(--aqt-rose)]"
              : meta.isCompleted
                ? "text-[var(--aqt-fg-dim)]"
                : "text-[var(--aqt-fg-muted)]"
          )}
        >
          {meta.isLive && (
            <span
              className="h-1.5 w-1.5 animate-pulse rounded-full"
              style={{ background: "var(--aqt-rose)" }}
            />
          )}
          {meta.timeLabel}
        </span>
      </div>
    </div>
  );
}

function resultStatusBadge(encounter: Encounter) {
  const status = encounter.result_status;
  if (!status || status === "none") return null;
  if (status === "confirmed") return null;
  const label =
    status === "pending_confirmation" ? "Ожидает" : status === "disputed" ? "Спор" : status;
  const color =
    status === "pending_confirmation"
      ? "bg-amber-500/80"
      : status === "disputed"
        ? "bg-red-500/80"
        : "bg-white/40";
  return (
    <span
      className={`absolute left-1 top-1 rounded px-1 text-[9px] font-semibold uppercase text-white ${color}`}
    >
      {label}
    </span>
  );
}

export function BracketView({
  encounters,
  type,
  onEdit,
  onReport,
  canEdit,
  canReport
}: BracketViewProps) {
  const { t } = useTranslation();
  const [hoveredTeamId, setHoveredTeamId] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const panRef = useRef({ active: false, startX: 0, startY: 0, left: 0, top: 0 });
  const [isGrabbing, setIsGrabbing] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    if (!isFullscreen) return;
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsFullscreen(false);
    };
    document.addEventListener("keydown", handleEsc);
    return () => document.removeEventListener("keydown", handleEsc);
  }, [isFullscreen]);

  useEffect(() => {
    if (isFullscreen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isFullscreen]);

  const layout = useMemo(() => buildLayout(encounters, type), [encounters, type]);

  // Drag-to-pan with the mouse; touch keeps native scrolling.
  const handlePanStart = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== "mouse" || event.button !== 0) return;
    if ((event.target as HTMLElement).closest("button, a")) return;
    const el = scrollRef.current;
    if (!el) return;
    panRef.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      left: el.scrollLeft,
      top: el.scrollTop
    };
    el.setPointerCapture?.(event.pointerId);
    setIsGrabbing(true);
  };
  const handlePanMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const pan = panRef.current;
    const el = scrollRef.current;
    if (!pan.active || !el) return;
    el.scrollLeft = pan.left - (event.clientX - pan.startX);
    el.scrollTop = pan.top - (event.clientY - pan.startY);
  };
  const handlePanEnd = (event: React.PointerEvent<HTMLDivElement>) => {
    const el = scrollRef.current;
    if (el?.hasPointerCapture?.(event.pointerId)) el.releasePointerCapture(event.pointerId);
    panRef.current.active = false;
    setIsGrabbing(false);
  };

  if (layout.nodes.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground">No bracket matches to display</div>
    );
  }

  return (
    <div
      className={cn(
        "relative overflow-hidden rounded-2xl border border-[var(--aqt-border)] bg-[var(--aqt-bg-2)] transition-all duration-300",
        isFullscreen && "fixed inset-0 z-50 rounded-none border-none bg-[var(--aqt-bg)] p-6 flex flex-col h-screen w-screen"
      )}
    >
      {isFullscreen && (
        <div className="mb-4 flex items-center justify-between border-b border-[var(--aqt-border)] pb-3">
          <div>
            <h2 className="text-xl font-bold text-white uppercase tracking-wider">
              {type === "double_elimination"
                ? "Double Elimination"
                : type === "single_elimination"
                  ? "Single Elimination"
                  : "Bracket"}
            </h2>
            <p className="text-xs text-[var(--aqt-fg-muted)]">
              {t("common.bracketInstructions")}
            </p>
          </div>
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--aqt-border)] bg-[hsl(0_0%_0%/0.25)] text-[var(--aqt-fg-muted)] hover:text-white transition-colors"
            onClick={() => setIsFullscreen(false)}
            title={t("common.bracketExitFullscreen")}
          >
            <Minimize2 className="h-4.5 w-4.5" />
          </button>
        </div>
      )}

      {!isFullscreen && (
        <div className="absolute right-4 top-4 z-10">
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[var(--aqt-border)] bg-[hsl(0_0%_0%/0.6)] text-[var(--aqt-fg-muted)] hover:text-white transition-colors"
            onClick={() => setIsFullscreen(true)}
            title={t("common.bracketFullscreen")}
          >
            <Maximize2 className="h-4.5 w-4.5" />
          </button>
        </div>
      )}

      <div
        ref={scrollRef}
        className={cn(
          "select-none overflow-auto",
          isFullscreen ? "flex-1 w-full h-full" : "max-h-[78vh]",
          isGrabbing ? "cursor-grabbing" : "cursor-grab"
        )}
        onPointerDown={handlePanStart}
        onPointerMove={handlePanMove}
        onPointerUp={handlePanEnd}
        onPointerCancel={handlePanEnd}
      >
        <div
          className="relative min-w-full"
          style={{
            width: layout.width,
            height: layout.height,
            backgroundImage:
              "radial-gradient(circle at 1px 1px, hsl(0 0% 100% / 0.05) 1px, transparent 0)",
            backgroundSize: "22px 22px"
          }}
        >
          <svg
            className="pointer-events-none absolute inset-0"
            width={layout.width}
            height={layout.height}
            viewBox={`0 0 ${layout.width} ${layout.height}`}
            fill="none"
          >
            {layout.edges.map((edge) => (
              <path
                key={edge.id}
                d={edge.path}
                stroke={
                  edge.isCompleted ? "hsl(174 72% 46% / 0.55)" : "hsl(0 0% 100% / 0.12)"
                }
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            ))}
          </svg>

          {layout.headers.map((header) => (
            <div
              key={header.id}
              className="absolute"
              style={{ left: header.x, top: header.y, width: CARD_WIDTH }}
            >
              <div className="inline-flex items-center gap-2 rounded-full border border-[var(--aqt-border-2)] bg-[hsl(0_0%_0%/0.45)] px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.18em] text-[var(--aqt-fg-muted)]">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{
                    background:
                      header.section === "upper" ? "var(--aqt-teal)" : "var(--aqt-blue)"
                  }}
                />
                <span>{header.label}</span>
              </div>
            </div>
          ))}

          {layout.nodes.map((node) => {
            const editable = onEdit && (canEdit?.(node.encounter) ?? true);
            const reportable = onReport && (canReport?.(node.encounter) ?? false);
            return (
              <div
                key={node.id}
                className="group absolute"
                style={{ left: node.x, top: node.y, width: CARD_WIDTH, height: CARD_HEIGHT }}
              >
                <MatchCard
                  data={node.data}
                  encounter={node.encounter}
                  hoveredTeamId={hoveredTeamId}
                  onHoveredTeamChange={setHoveredTeamId}
                />
                <div
                  className="pointer-events-none absolute top-1/2 -translate-y-1/2"
                  style={{ left: CARD_WIDTH + 6 }}
                >
                  <span className="font-mono text-[12px] font-semibold text-[var(--aqt-fg-muted)]">
                    {node.data.matchLabel}
                  </span>
                </div>
                {resultStatusBadge(node.encounter)}
                {(editable || reportable) && (
                  <div className="absolute right-1 top-1 flex gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                    {editable && (
                      <button
                        type="button"
                        className="rounded-md border border-[var(--aqt-border-2)] bg-[hsl(0_0%_0%/0.6)] p-1 text-[var(--aqt-fg-muted)] hover:text-[var(--aqt-fg)]"
                        aria-label="Редактировать матч"
                        onClick={(e) => {
                          e.stopPropagation();
                          onEdit?.(node.encounter);
                        }}
                      >
                        <Pencil className="h-3 w-3" />
                      </button>
                    )}
                    {reportable && (
                      <button
                        type="button"
                        className="rounded-md border border-[hsl(174_72%_46%/0.3)] bg-[hsl(174_72%_46%/0.16)] p-1 text-[var(--aqt-teal)] hover:bg-[hsl(174_72%_46%/0.24)]"
                        aria-label="Репорт матча"
                        onClick={(e) => {
                          e.stopPropagation();
                          onReport?.(node.encounter);
                        }}
                      >
                        <FileEdit className="h-3 w-3" />
                      </button>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
