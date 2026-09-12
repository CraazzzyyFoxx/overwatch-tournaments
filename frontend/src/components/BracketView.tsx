"use client";

import { useMemo, useRef, useState } from "react";
import { Pencil, FileEdit, ListChecks, Maximize2, Search } from "lucide-react";
import { HoverPrefetchLink } from "@/components/HoverPrefetchLink";
import { usePathname, useSearchParams } from "next/navigation";

import { useFormatter, useTranslations } from "next-intl";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { STREAM_STATUS_META } from "@/lib/stream-platform";
import type { StreamEntry } from "@/types/stream.types";
import type { StageType } from "@/types/tournament.types";
import { EncounterRostersModal } from "@/components/EncounterRostersModal";
import TeamName from "@/components/TeamName";
import { withReturnTo } from "@/lib/return-to";
import {
  activeRoundNumber,
  buildRoundGroups as buildBracketRoundGroups,
  computeMatchNumbers as computeBracketMatchNumbers,
  computeSlotHints as computeBracketSlotHints,
  getDoubleEliminationFinalRounds as getBracketFinalRounds,
  getRoundSectionMatchCapacity,
  orderEliminationRounds,
  type BracketMatch,
  type SlotHint
} from "@/components/bracket-view.helpers";
import {
  useBracketRoundLabel,
  type BracketRoundLabelFormatter
} from "@/hooks/useBracketRoundLabel";

type Translate = ReturnType<typeof useTranslations<never>>;
/** Only `dateTime` is needed here; `useFormatter()` and `await getFormatter()` both satisfy it. */
type DateFormatter = Pick<ReturnType<typeof useFormatter>, "dateTime">;

/**
 * Generic over the row type so an action handler can keep taking the caller's
 * OWN match type: the public bracket's `onEdit` needs a full `Encounter`, and a
 * callback typed on the wider `BracketMatch` would not accept it (parameters
 * are contravariant). The layout below stays non-generic — it reads only
 * `BracketMatch` fields — so the handoff back to `M` happens at the four call
 * sites that invoke these callbacks.
 */
interface BracketViewProps<M extends BracketMatch> {
  encounters: M[];
  type: StageType;
  onEdit?: (encounter: M) => void;
  onReport?: (encounter: M) => void;
  canEdit?: (encounter: M) => boolean;
  canReport?: (encounter: M) => boolean;
  /**
   * Team id → the stream of whoever from that team is on air, keyed by the same
   * id `Encounter.home_team_id`/`away_team_id` carry.
   *
   * Optional on purpose: this component is shared with the admin bracket, which
   * has no stream query behind it. Making a public-only affordance required
   * would force that call site to invent an empty map for nothing.
   */
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  /**
   * Whether a card links out (match page, rosters, pre-game room).
   *
   * Off for the admin bracket preview, whose matches are the generator's
   * skeleton and have no encounter row to link to yet — the tree is the same,
   * only the destinations do not exist.
   */
  interactive?: boolean;
  /**
   * Encounter id to bring into view and outline on mount — the `?match=` deep
   * link the overview and matches sections use to point at one node.
   */
  highlightMatchId?: number | null;
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
  encounter: BracketMatch;
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
  matches: BracketMatch[];
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
// Breathing room between a round header and the first card under it.
const HEADER_GAP_Y = 14;
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

function getMatchNames(match: BracketMatch) {
  const parsed = splitEncounterName(match.name);

  return {
    homeName: match.home_team?.name?.trim() || parsed.homeName || "TBD",
    awayName: match.away_team?.name?.trim() || parsed.awayName || "TBD"
  };
}

function getWinner(match: BracketMatch): "home" | "away" | null {
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
  match: BracketMatch,
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

function addWinnerSourceEdges(
  nodes: LayoutNode[],
  nodesById: Map<string, LayoutNode>,
  edges: LayoutEdge[]
) {
  const seen = new Set<string>();
  for (const node of nodes) {
    for (const source of node.encounter.sources ?? []) {
      if (source.role !== "winner") continue;
      const edgeId = `edge-${source.encounter_id}-${node.encounter.id}`;
      if (seen.has(edgeId)) continue;
      const sourceNode = nodesById.get(`match-${source.encounter_id}`);
      if (!sourceNode) continue;
      seen.add(edgeId);
      edges.push({
        id: edgeId,
        path: buildPath(sourceNode, node),
        isCompleted: COMPLETED_STATUSES.has(sourceNode.encounter.status)
      });
    }
  }
}

// Shared by the upper, lower, and grand-final columns: each pushes one round
// header then lays out that round's matches at a fixed `CARD_HEIGHT +
// MATCH_GAP_Y` pitch from a caller-computed `startY`. Only the header
// placement/section and the vertical anchor differ between sections.
function layoutBracketColumn(params: {
  group: RoundGroup;
  x: number;
  headerY: number;
  headerId: string;
  headerSection: "upper" | "lower";
  label: string;
  startY: number;
  slotHints: Map<number, SlotHint>;
  matchNumbers: Map<number, number>;
  headers: LayoutHeader[];
  nodes: LayoutNode[];
}) {
  const { group, x, headerY, headerId, headerSection, label, startY, slotHints, matchNumbers, headers, nodes } =
    params;

  headers.push({ id: headerId, x, y: headerY, label, section: headerSection });

  group.matches.forEach((match, matchIndex) => {
    const hint = slotHints.get(match.id) ?? { home: null, away: null };
    const n = matchNumbers.get(match.id) ?? 0;
    nodes.push(
      createNode(match, x, startY + matchIndex * (CARD_HEIGHT + MATCH_GAP_Y), n, hint.home, hint.away)
    );
  });
}

function buildLayout(
  encounters: BracketMatch[],
  type: StageType,
  _t: Translate,
  roundLabel: BracketRoundLabelFormatter
): BracketLayout {
  const hasBracketConnections = type === "single_elimination" || type === "double_elimination";

  const isDE = type === "double_elimination";
  const finalRoundNumbers = isDE ? getBracketFinalRounds(encounters) : new Set<number>();
  // Ascending, so `bracketRoundLabel` reads the first entry as the Grand Final
  // and any later one as its reset.
  const finalRoundList = [...finalRoundNumbers].sort((left, right) => left - right);

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
  const upperTop = upperHeaderY + HEADER_HEIGHT + HEADER_GAP_Y;

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

    layoutBracketColumn({
      group,
      x,
      headerY: upperHeaderY,
      headerId: `upper-header-${group.round}`,
      headerSection: "upper",
      label: roundLabel(group.round, finalRoundList),
      startY,
      slotHints,
      matchNumbers,
      headers,
      nodes
    });
  });

  const hasLowerBracket = lowerRounds.length > 0;
  const lowerHeaderY = upperTop + upperSectionHeight + (hasLowerBracket ? SECTION_GAP_Y : 0);
  const lowerTop = lowerHeaderY + HEADER_HEIGHT + HEADER_GAP_Y;
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

    layoutBracketColumn({
      group,
      x,
      headerY: lowerHeaderY,
      headerId: `lower-header-${group.round}`,
      headerSection: "lower",
      label: roundLabel(group.round, finalRoundList),
      startY,
      slotHints,
      matchNumbers,
      headers,
      nodes
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
    // Centered in the bracket body, i.e. below the header row — otherwise the
    // card lands on top of its own header.
    const finalTop = PADDING_Y + HEADER_HEIGHT + HEADER_GAP_Y;
    const startY = finalTop + Math.max(0, (fullContentHeight - finalTop - totalHeight) / 2);

    layoutBracketColumn({
      group,
      x,
      headerY: PADDING_Y,
      headerId: `final-header-${group.round}`,
      headerSection: "upper",
      label: roundLabel(group.round, finalRoundList),
      startY,
      slotHints,
      matchNumbers,
      headers,
      nodes
    });
  });

  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  const recordedSources = nodes.some((node) => (node.encounter.sources?.length ?? 0) > 0);

  if (hasBracketConnections) {
    if (recordedSources) {
      addWinnerSourceEdges(nodes, nodesById, edges);
    } else {
      addSequentialEdges(upperRounds, nodesById, edges, (matchIndex, targetCount) => {
        const targetIndex = Math.floor(matchIndex / 2);
        return targetIndex < targetCount ? targetIndex : -1;
      });

      addSequentialEdges(lowerRounds, nodesById, edges, (matchIndex, targetCount) => {
        if (targetCount === 0) return -1;
        return Math.min(matchIndex, targetCount - 1);
      });
    }
  }

  if (isDE && finalRounds.length > 0) {
    const gfGroup = finalRounds[0];
    const gfMatch = gfGroup?.matches[0];
    const gfNode = gfMatch ? nodesById.get(`match-${gfMatch.id}`) : undefined;

    if (gfNode && !recordedSources) {
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

function getMatchMeta(encounter: BracketMatch, t: Translate, format: DateFormatter) {
  const isCompleted = COMPLETED_STATUSES.has(encounter.status);
  const isLive = !isCompleted && Boolean(encounter.started_at) && !encounter.ended_at;
  const played = (encounter.score?.home ?? 0) + (encounter.score?.away ?? 0);
  const bestOf = encounter.best_of ?? 0;

  let timeLabel = "";
  if (isLive) {
    timeLabel = t("common.live");
  } else if (!isCompleted && encounter.scheduled_at) {
    timeLabel = format.dateTime(new Date(encounter.scheduled_at), {
      month: "short",
      day: "numeric"
    });
  } else if (bestOf > 0) {
    timeLabel = `Bo${bestOf}`;
  }

  return { isCompleted, isLive, played, bestOf, timeLabel };
}

function MatchCard({
  data,
  encounter,
  hoveredTeamId,
  onHoveredTeamChange,
  returnTo,
  liveTeamStreams,
  interactive
}: Readonly<{
  data: MatchNodeData;
  encounter: BracketMatch;
  hoveredTeamId: number | null;
  onHoveredTeamChange: (teamId: number | null) => void;
  /** This bracket's own location, so the pre-game room can send viewers back to it. */
  returnTo: string;
  liveTeamStreams?: ReadonlyMap<number, StreamEntry>;
  /** `false` on a projected match: there is no encounter row to link to. */
  interactive: boolean;
}>) {
  const t = useTranslations();
  const format = useFormatter();
  const meta = getMatchMeta(encounter, t, format);
  const hasVisibleScore = data.isCompleted || data.homeScore !== 0 || data.awayScore !== 0;
  const footerHeight = CARD_HEIGHT - CARD_ROW_HEIGHT * 2;

  const getRowClasses = (side: "home" | "away") => {
    if (data.winner === side) {
      return "bg-[color:color-mix(in_srgb,var(--aqt-teal)_10%,transparent)] text-[color:var(--aqt-fg)] font-semibold";
    }
    if (data.winner && data.winner !== side) {
      return "text-[color:var(--aqt-fg-dim)]";
    }
    return "text-[color:var(--aqt-fg-muted)]";
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
      return source ?? t("common.tbd");
    }
    return name;
  };

  const isTbdSlot = (side: "home" | "away") =>
    (side === "home" ? data.homeName : data.awayName) === "TBD";

  // The participant stream on air for this slot's team, if any. A TBD slot has
  // no team, so it can never carry the indicator.
  const liveStreamFor = (side: "home" | "away") => {
    if (liveTeamStreams === undefined || isTbdSlot(side)) return undefined;
    const teamId = getTeamId(side);
    return teamId == null ? undefined : liveTeamStreams.get(teamId);
  };

  const renderRow = (side: "home" | "away") => {
    const score = side === "home" ? data.homeScore : data.awayScore;
    const won = data.winner === side;
    // An unfilled slot shows a hint ("Winner of M3") rather than a team, so it
    // gets no logo — `data.*Name` is also the source of a name parsed out of the
    // encounter title when the team relation itself is missing.
    const isTbd = isTbdSlot(side);
    const slotTeam = isTbd ? null : (side === "home" ? encounter.home_team : encounter.away_team);
    const liveStream = liveStreamFor(side);
    // The map only ever holds participant entries, which always carry a player;
    // the channel fallback exists because `player` is nullable on the wire (an
    // official broadcast has none).
    const streamer =
      liveStream === undefined ? null : (liveStream.player?.name ?? liveStream.channel);
    // A bare dot says "something is happening" and nothing else, so the whole
    // point of the indicator is this string: it names the player and, when the
    // platform reports one, the audience.
    const liveLabel =
      liveStream === undefined || streamer === null
        ? null
        : liveStream.viewer_count == null
          ? t("bracket.liveTeamStream", { player: streamer })
          : t("bracket.liveTeamStreamWithViewers", {
              player: streamer,
              count: liveStream.viewer_count
            });
    return (
      <div
        className={cn(
          "flex items-center justify-between gap-2 px-2.5 transition-colors",
          side === "home" && "border-b border-[color:var(--aqt-border)]",
          getRowClasses(side),
          isHighlighted(side) &&
            "bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] text-[color:var(--aqt-fg)]"
        )}
        data-team-id={getTeamId(side) ?? undefined}
        data-team-highlighted={isHighlighted(side) || undefined}
        onPointerEnter={() => handlePointerEnter(side)}
        onPointerLeave={() => handlePointerLeave(side)}
        style={{ height: CARD_ROW_HEIGHT }}
      >
        {/* Name and dot share one shrinking group so the score stays pinned to
            the right edge at exactly the position it had before the indicator
            existed — the row is a fixed CARD_ROW_HEIGHT with nowhere to spill. */}
        <span className="flex min-w-0 items-center gap-1.5">
          <TeamName
            team={slotTeam}
            fallback={getDisplayName(side)}
            size="xs"
            nameClassName={
              isTbd ? "text-label italic text-[color:var(--aqt-fg-faint)]" : "text-caption"
            }
          />
          {liveStream !== undefined && liveLabel !== null ? (
            <span
              // Indication, NOT navigation. A ~13px target wedged between a
              // truncated team name and its score is a pointer-target defect on
              // touch and a pointless extra tab stop on a 32-team tree, and the
              // Streams tab already lists every channel as a full-sized link. So
              // this is a labelled image with no href.
              role="img"
              aria-label={liveLabel}
              title={liveLabel}
              data-live-team-stream={liveStream.channel}
              // The site's one liveness language: the pulsing rose `.dot` exists
              // only under `.status-pill.live` in `globals.css`, so the class has
              // to be here for the descendant selector to match. The inline style
              // strips the pill's own chrome, which does not belong in a 30px row
              // — same mechanism `TournamentsTable` uses to shrink this pill for
              // its dense rows, and the only one that beats an `.aqt-tn`-scoped
              // selector's specificity.
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
  };

  return (
    <div
      className={cn(
        "relative flex h-full flex-col overflow-hidden rounded-[10px] border bg-[color:var(--aqt-card)] shadow-[0_10px_24px_rgba(0,0,0,0.28)]",
        meta.isLive
          ? "border-[color:color-mix(in_srgb,var(--aqt-rose)_45%,transparent)]"
          : data.winner
            ? "border-[color:var(--aqt-border-2)]"
            : "border-[color:var(--aqt-border)]"
      )}
    >
      {renderRow("home")}
      {renderRow("away")}

      <div
        className="flex items-center justify-between gap-2 border-t border-[color:var(--aqt-border)] bg-[hsl(0_0%_100%/0.015)] px-2.5"
        style={{ height: footerHeight }}
      >
        {interactive ? (
          <div className="flex items-center gap-2">
            <HoverPrefetchLink
              href={`/encounters/${encounter.id}`}
              className="flex items-center justify-center rounded p-0.5 text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              aria-label={t("bracket.viewMatch")}
              onClick={(e) => {
                // Keep any future card-level click handler from also firing.
                e.stopPropagation();
              }}
            >
              <Search className="size-3.5" aria-hidden />
            </HoverPrefetchLink>
            {/* The roster peek stays on the bracket: a scroll position built up
                over a 32-team tree survives looking at who is playing. The
                pre-game link leaves, because the room is where a captain acts —
                a read-only copy of its veto in a dialog was a second door onto
                one phase and earned neither the icon nor the fetch. */}
            <EncounterRostersModal
              encounterId={encounter.id}
              homeTeamName={encounter.home_team?.name ?? t("common.tbd")}
              awayTeamName={encounter.away_team?.name ?? t("common.tbd")}
            />
            <HoverPrefetchLink
              href={withReturnTo(
                `/tournaments/${encounter.tournament_id}/pregame/${encounter.id}`,
                returnTo
              )}
              className="flex items-center justify-center rounded p-0.5 text-[color:var(--aqt-fg-muted)] transition-colors hover:bg-[color:var(--aqt-overlay-3)] hover:text-[color:var(--aqt-fg)]"
              aria-label={t("bracket.pregameRoom")}
              onClick={(e) => {
                e.stopPropagation();
              }}
            >
              <ListChecks className="size-3.5" aria-hidden />
            </HoverPrefetchLink>
          </div>
        ) : (
          <span />
        )}
        {meta.timeLabel && (
          <span
            className={cn(
              "flex items-center gap-1 text-label font-semibold uppercase tracking-wide",
              meta.isLive ? "text-[color:var(--aqt-rose)]" : "text-[color:var(--aqt-fg-muted)]"
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
        )}
      </div>
    </div>
  );
}

function resultStatusBadge(encounter: BracketMatch, t: Translate) {
  const status = encounter.result_status;
  if (!status || status === "none") return null;
  if (status === "confirmed") return null;
  const label =
    status === "pending_confirmation"
      ? t("bracket.pending")
      : status === "disputed"
        ? t("bracket.disputed")
        : status;
  const color =
    status === "pending_confirmation"
      ? "var(--aqt-amber)"
      : status === "disputed"
        ? "var(--aqt-rose)"
        : "var(--aqt-fg-faint)";
  return (
    <span
      className="absolute left-1 top-1 rounded px-1 text-label font-semibold uppercase"
      style={{ background: color, color: "var(--aqt-bg)" }}
    >
      {label}
    </span>
  );
}

export function BracketView<M extends BracketMatch>({
  encounters,
  type,
  onEdit,
  onReport,
  canEdit,
  canReport,
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
  const panRef = useRef<{
    active: boolean;
    startX: number;
    startY: number;
    left: number;
    top: number;
    el: HTMLDivElement | null;
  }>({ active: false, startX: 0, startY: 0, left: 0, top: 0, el: null });
  const [isGrabbing, setIsGrabbing] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);

  const roundLabel = useBracketRoundLabel();
  const layout = useMemo(
    () => buildLayout(encounters, type, t, roundLabel),
    [encounters, type, t, roundLabel]
  );

  // Scroll the deep-linked node into view once, after layout. A ref callback
  // rather than an effect keyed on the DOM: the node mounts inside the canvas
  // which itself mounts twice (inline + fullscreen), so the callback fires per
  // instance and the inline one is the one on screen.
  const highlightedRef = (node: HTMLDivElement | null) => {
    if (!node || highlightMatchId === null) return;
    node.scrollIntoView({ block: "center", inline: "center" });
  };

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

  // Applied per scroller element, once. `dataset` rather than a ref flag
  // because the inline canvas and the fullscreen one are two elements, and
  // because a re-render (hover, a poll landing) must not yank a viewer who has
  // already panned somewhere else.
  const focusScroller = (el: HTMLDivElement | null) => {
    if (!el || !focus || el.dataset.bracketFocused) return;
    el.dataset.bracketFocused = "1";
    el.scrollLeft = Math.max(0, focus.x - (el.clientWidth - CARD_WIDTH) / 2);
    el.scrollTop = Math.max(0, focus.y - (el.clientHeight - CARD_HEIGHT) / 2);
  };

  // Drag-to-pan with the mouse; touch keeps native scrolling. The scroller is
  // the event target, so the same handlers serve the inline and the fullscreen
  // copy without a shared ref pointing at whichever mounted last.
  const handlePanStart = (event: React.PointerEvent<HTMLDivElement>) => {
    if (event.pointerType !== "mouse" || event.button !== 0) return;
    if ((event.target as HTMLElement).closest("button, a")) return;
    const el = event.currentTarget;
    panRef.current = {
      active: true,
      startX: event.clientX,
      startY: event.clientY,
      left: el.scrollLeft,
      top: el.scrollTop,
      el
    };
    el.setPointerCapture?.(event.pointerId);
    setIsGrabbing(true);
  };
  const handlePanMove = (event: React.PointerEvent<HTMLDivElement>) => {
    const pan = panRef.current;
    if (!pan.active || !pan.el) return;
    pan.el.scrollLeft = pan.left - (event.clientX - pan.startX);
    pan.el.scrollTop = pan.top - (event.clientY - pan.startY);
  };
  const handlePanEnd = (event: React.PointerEvent<HTMLDivElement>) => {
    const el = panRef.current.el;
    if (el?.hasPointerCapture?.(event.pointerId)) el.releasePointerCapture(event.pointerId);
    panRef.current.active = false;
    panRef.current.el = null;
    setIsGrabbing(false);
  };

  if (layout.nodes.length === 0) {
    return (
      <div className="py-8 text-center text-muted-foreground">{t("common.noBracketMatches")}</div>
    );
  }

  const bracketTitle =
    type === "double_elimination"
      ? t("bracket.doubleElimination")
      : type === "single_elimination"
        ? t("bracket.singleElimination")
        : t("common.bracket");

  const canvas = (fullscreen: boolean) => (
    <div
      ref={focusScroller}
      className={cn(
        "select-none overflow-auto",
        fullscreen ? "h-full w-full flex-1" : "max-h-[78vh]",
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
          aria-hidden
        >
          {layout.edges.map((edge) => (
            <path
              key={edge.id}
              d={edge.path}
              stroke={
                edge.isCompleted
                  ? "color-mix(in srgb, var(--aqt-teal) 55%, transparent)"
                  : "hsl(0 0% 100% / 0.12)"
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
            data-round-header={header.id}
            className="absolute"
            style={{ left: header.x, top: header.y, width: CARD_WIDTH }}
          >
            <div className="inline-flex items-center gap-2 rounded-full border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_0%/0.45)] px-2.5 py-0.5 text-label font-semibold uppercase tracking-label text-[color:var(--aqt-fg-muted)]">
              <span
                aria-hidden
                className="h-2 w-2 rounded-full"
                style={{
                  background: header.section === "upper" ? "var(--aqt-teal)" : "var(--aqt-blue)"
                }}
              />
              <span>{header.label}</span>
            </div>
          </div>
        ))}

        {layout.nodes.map((node) => {
          // Every node was built from `encounters: M[]`, so its row IS an `M`;
          // the layout types drop that down to `BracketMatch` because nothing
          // in them reads more than that.
          const match = node.encounter as M;
          const editable = onEdit && (canEdit?.(match) ?? true);
          const reportable = onReport && (canReport?.(match) ?? false);
          const highlighted = highlightMatchId !== null && match.id === highlightMatchId;
          return (
            <div
              key={node.id}
              ref={highlighted ? highlightedRef : undefined}
              data-match-id={match.id}
              className={cn("group absolute", highlighted && "rounded-[10px] ring-2 ring-[color:var(--aqt-teal)] ring-offset-2 ring-offset-[color:var(--aqt-card)]")}
              style={{ left: node.x, top: node.y, width: CARD_WIDTH, height: CARD_HEIGHT }}
            >
              <MatchCard
                data={node.data}
                encounter={node.encounter}
                hoveredTeamId={hoveredTeamId}
                onHoveredTeamChange={setHoveredTeamId}
                returnTo={returnTo}
                liveTeamStreams={liveTeamStreams}
                interactive={interactive}
              />
              <div
                className="pointer-events-none absolute top-1/2 -translate-y-1/2"
                style={{ left: CARD_WIDTH + 6 }}
              >
                <span className="text-label font-semibold tabular-nums text-[color:var(--aqt-fg-muted)]">
                  {node.data.matchLabel}
                </span>
              </div>
              {resultStatusBadge(node.encounter, t)}
              {(editable || reportable) && (
                // Revealed on focus as well as hover: `opacity-0` alone leaves
                // these focusable but invisible, so keyboard focus vanished here.
                <div className="absolute right-1 top-1 flex gap-1 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
                  {editable && (
                    <button
                      type="button"
                      className="rounded-md border border-[color:var(--aqt-border-2)] bg-[hsl(0_0%_0%/0.6)] p-1 text-[color:var(--aqt-fg-muted)] hover:text-[color:var(--aqt-fg)]"
                      aria-label={t("bracket.editMatch")}
                      onClick={(e) => {
                        e.stopPropagation();
                        onEdit?.(match);
                      }}
                    >
                      <Pencil className="h-3 w-3" aria-hidden />
                    </button>
                  )}
                  {reportable && (
                    <button
                      type="button"
                      className="rounded-md border border-[color:color-mix(in_srgb,var(--aqt-teal)_30%,transparent)] bg-[color:color-mix(in_srgb,var(--aqt-teal)_16%,transparent)] p-1 text-[color:var(--aqt-teal)] hover:bg-[color:color-mix(in_srgb,var(--aqt-teal)_24%,transparent)]"
                      aria-label={t("bracket.reportMatch")}
                      onClick={(e) => {
                        e.stopPropagation();
                        onReport?.(match);
                      }}
                    >
                      <FileEdit className="h-3 w-3" aria-hidden />
                    </button>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );

  return (
    <>
      <div className="relative overflow-hidden rounded-2xl border border-[color:var(--aqt-border)] bg-[color:var(--aqt-bg-2)]">
        <div className="absolute right-4 top-4 z-10">
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-[color:var(--aqt-border)] bg-[hsl(0_0%_0%/0.6)] text-[color:var(--aqt-fg-muted)] outline-none transition-colors hover:text-[color:var(--aqt-fg)] focus-visible:ring-2 focus-visible:ring-[color:var(--aqt-teal)]"
            onClick={() => setIsFullscreen(true)}
            aria-label={t("common.bracketFullscreen")}
          >
            <Maximize2 className="h-4.5 w-4.5" aria-hidden />
          </button>
        </div>

        {canvas(false)}
      </div>

      {/* Radix owns the modal contract the hand-rolled overlay never had:
          role="dialog", aria-modal, a focus trap, focus restore on close and
          scroll locking. Escape came for free there; nothing else did. */}
      <Dialog open={isFullscreen} onOpenChange={setIsFullscreen}>
        <DialogContent className="left-0 top-0 flex h-screen w-screen max-w-none translate-x-0 translate-y-0 flex-col gap-0 rounded-none border-none bg-[color:var(--aqt-bg)] p-6">
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

          {isFullscreen ? canvas(true) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
