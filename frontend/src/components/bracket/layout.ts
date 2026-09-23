/**
 * The bracket tree's geometry: where every card, connector and round header
 * sits, as plain numbers. No React in here, so a layout can be asserted in a
 * test the way a viewer sees it — column x, card y, which edges exist.
 */
import type { BracketRoundLabelFormatter } from "@/hooks/useBracketRoundLabel";
import type { StageType } from "@/types/tournament.types";

import {
  bracketRoundShape,
  buildRoundGroups,
  computeMatchNumbers,
  computeSlotHints,
  getDoubleEliminationFinalRounds,
  getRoundSectionMatchCapacity,
  type BracketMatch,
  type RoundGroup,
  type SlotHint
} from "@/lib/bracket/view";
import { isEncounterCompleted } from "@/lib/encounter/status";

/** The match-number strip down a card's left edge; part of `CARD_WIDTH`. */
export const GUTTER_WIDTH = 26;
export const CARD_WIDTH = 210 + GUTTER_WIDTH;
export const CARD_HEIGHT = 84;
export const CARD_ROW_HEIGHT = 30;
export const ROUND_GAP_X = 48;
export const MATCH_GAP_Y = 10;
export const HEADER_HEIGHT = 24;
// Breathing room between a round header and the first card under it.
export const HEADER_GAP_Y = 14;
export const SECTION_GAP_Y = 52;
export const PADDING_X = 16;
export const PADDING_Y = 14;

export type Side = "home" | "away";

export interface MatchNodeData {
  matchNumber: number;
  /** `M<matchNumber>`: the key a TBD slot's "W M3" hint points at. */
  matchLabel: string;
  homeName: string;
  awayName: string;
  homeSource: string | null;
  awaySource: string | null;
  homeTeamId: number | null;
  awayTeamId: number | null;
  /**
   * This is the team's newest match in the tree — the one it is playing or
   * waiting to play. A result awaiting confirmation can leave the winner
   * standing in two open matches; "streaming now" belongs on the newer.
   */
  homeIsLatest: boolean;
  awayIsLatest: boolean;
  homeScore: number;
  awayScore: number;
  winner: Side | null;
  isCompleted: boolean;
}

export interface LayoutNode {
  id: string;
  x: number;
  y: number;
  data: MatchNodeData;
  encounter: BracketMatch;
}

export interface LayoutEdge {
  id: string;
  path: string;
  isCompleted: boolean;
  sourceId: number;
  targetId: number;
  /** The team that travelled this connector — the source's winner once it is settled. */
  teamId: number | null;
}

export interface LayoutHeader {
  id: string;
  x: number;
  y: number;
  label: string;
  section: "upper" | "lower";
}

export interface BracketLayout {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  headers: LayoutHeader[];
  width: number;
  height: number;
}

const NAME_SEPARATORS = [" vs. ", " vs ", " VS ", " - ", " v "];

function splitEncounterName(name: string | null | undefined) {
  const value = name?.trim();
  if (!value) return { homeName: null, awayName: null };

  for (const separator of NAME_SEPARATORS) {
    if (!value.includes(separator)) continue;
    const [homeName, awayName] = value.split(separator, 2).map((part) => part.trim());
    if (homeName && awayName) return { homeName, awayName };
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

export function getWinner(match: BracketMatch): Side | null {
  if (!isEncounterCompleted(match)) return null;
  if (match.score.home === match.score.away) return null;
  return match.score.home > match.score.away ? "home" : "away";
}

function winnerTeamId(match: BracketMatch): number | null {
  const side = getWinner(match);
  if (side === null) return null;
  const id = side === "home" ? match.home_team_id : match.away_team_id;
  return id > 0 ? id : null;
}

/** Corner radius of a connector's two elbows. */
const ELBOW_RADIUS = 8;

/**
 * Source's right edge → across → down/up → into the target's left edge.
 *
 * The vertical run sits in the gap just before the TARGET column, not just after
 * the source: for neighbouring rounds the two are the same gap, but a connector
 * that spans columns (upper final → grand final over the whole lower bracket)
 * then travels along its own row, where nothing is drawn, and turns only at the
 * end — instead of dropping at once and cutting across every column between.
 * Both feeders of one match therefore share one vertical bar at its door.
 */
function buildPath(source: LayoutNode, target: LayoutNode) {
  const startX = source.x + CARD_WIDTH;
  const startY = source.y + CARD_HEIGHT / 2;
  const endX = target.x;
  const endY = target.y + CARD_HEIGHT / 2;
  const middleX = Math.max(startX, endX - ROUND_GAP_X / 2);
  const dy = endY - startY;
  const r = Math.min(ELBOW_RADIUS, Math.abs(dy) / 2, (middleX - startX) / 2, (endX - middleX) / 2);
  if (r < 1) return `M ${startX} ${startY} H ${middleX} V ${endY} H ${endX}`;
  const dir = Math.sign(dy);
  return [
    `M ${startX} ${startY}`,
    `H ${middleX - r}`,
    `Q ${middleX} ${startY} ${middleX} ${startY + dir * r}`,
    `V ${endY - dir * r}`,
    `Q ${middleX} ${endY} ${middleX + r} ${endY}`,
    `H ${endX}`
  ].join(" ");
}

function edgeBetween(source: LayoutNode, target: LayoutNode): LayoutEdge {
  return {
    id: `edge-${source.encounter.id}-${target.encounter.id}`,
    path: buildPath(source, target),
    isCompleted: isEncounterCompleted(source.encounter),
    sourceId: source.encounter.id,
    targetId: target.encounter.id,
    teamId: winnerTeamId(source.encounter)
  };
}

function createNode(
  match: BracketMatch,
  x: number,
  y: number,
  matchNumber: number,
  hint: SlotHint,
  latestMatchByTeam: Map<number, number>
): LayoutNode {
  const names = getMatchNames(match);
  return {
    id: `match-${match.id}`,
    x,
    y,
    data: {
      matchNumber,
      matchLabel: `M${matchNumber}`,
      homeName: names.homeName,
      awayName: names.awayName,
      homeSource: names.homeName === "TBD" ? hint.home : null,
      awaySource: names.awayName === "TBD" ? hint.away : null,
      homeTeamId: match.home_team_id > 0 ? match.home_team_id : null,
      awayTeamId: match.away_team_id > 0 ? match.away_team_id : null,
      homeIsLatest: latestMatchByTeam.get(match.home_team_id) === match.id,
      awayIsLatest: latestMatchByTeam.get(match.away_team_id) === match.id,
      homeScore: match.score.home,
      awayScore: match.score.away,
      winner: getWinner(match),
      isCompleted: isEncounterCompleted(match)
    },
    encounter: match
  };
}

function addSequentialEdges(
  groups: RoundGroup[],
  nodesById: Map<string, LayoutNode>,
  edges: LayoutEdge[],
  wiredTargets: ReadonlySet<number>,
  mapper: (matchIndex: number, targetCount: number) => number
) {
  for (let groupIndex = 0; groupIndex < groups.length - 1; groupIndex++) {
    const current = groups[groupIndex].matches;
    const next = groups[groupIndex + 1].matches;

    for (let matchIndex = 0; matchIndex < current.length; matchIndex++) {
      const targetIndex = mapper(matchIndex, next.length);
      if (targetIndex < 0 || targetIndex >= next.length) continue;
      // The match says where its teams come from: never guess over it.
      if (wiredTargets.has(next[targetIndex].id)) continue;

      const sourceNode = nodesById.get(`match-${current[matchIndex].id}`);
      const targetNode = nodesById.get(`match-${next[targetIndex].id}`);
      if (!sourceNode || !targetNode) continue;

      edges.push(edgeBetween(sourceNode, targetNode));
    }
  }
}

/**
 * Winner lines from the bracket's own advancement edges.
 *
 * Returns the encounters whose feeders are recorded (any role — a lower-bracket
 * drop is a `loser` edge), so column-index inference can fill in only the
 * matches that have no provenance of their own, instead of being switched off
 * for the whole bracket by a single wired match.
 */
function addWinnerSourceEdges(
  nodes: LayoutNode[],
  nodesById: Map<string, LayoutNode>,
  edges: LayoutEdge[]
): Set<number> {
  const wired = new Set<number>();
  const seen = new Set<string>();
  for (const node of nodes) {
    const sources = node.encounter.sources ?? [];
    if (sources.length > 0) wired.add(node.encounter.id);
    for (const source of sources) {
      if (source.role !== "winner") continue;
      const sourceNode = nodesById.get(`match-${source.encounter_id}`);
      if (!sourceNode) continue;
      const edge = edgeBetween(sourceNode, node);
      if (seen.has(edge.id)) continue;
      seen.add(edge.id);
      edges.push(edge);
    }
  }
  return wired;
}

function sectionHeight(matchCount: number) {
  return Math.max(matchCount * CARD_HEIGHT + Math.max(matchCount - 1, 0) * MATCH_GAP_Y, CARD_HEIGHT);
}

// Shared by the upper, lower, and grand-final columns: each pushes one round
// header then lays out that round's matches at a fixed `CARD_HEIGHT +
// MATCH_GAP_Y` pitch from a caller-computed `startY`.
function layoutColumn(params: {
  group: RoundGroup;
  x: number;
  headerY: number;
  headerId: string;
  headerSection: "upper" | "lower";
  label: string;
  startY: number;
  slotHints: Map<number, SlotHint>;
  matchNumbers: Map<number, number>;
  latestMatchByTeam: Map<number, number>;
  headers: LayoutHeader[];
  nodes: LayoutNode[];
}) {
  const { group, x, headerY, headerId, headerSection, label, startY, slotHints, matchNumbers, latestMatchByTeam } =
    params;

  params.headers.push({ id: headerId, x, y: headerY, label, section: headerSection });

  group.matches.forEach((match, matchIndex) => {
    const hint = slotHints.get(match.id) ?? { home: null, away: null };
    const n = matchNumbers.get(match.id) ?? 0;
    params.nodes.push(
      createNode(match, x, startY + matchIndex * (CARD_HEIGHT + MATCH_GAP_Y), n, hint, latestMatchByTeam)
    );
  });
}

export function buildLayout(
  encounters: BracketMatch[],
  type: StageType,
  roundLabel: BracketRoundLabelFormatter
): BracketLayout {
  const hasBracketConnections = type === "single_elimination" || type === "double_elimination";
  const isDE = type === "double_elimination";
  const finalRoundNumbers = isDE ? getDoubleEliminationFinalRounds(encounters) : new Set<number>();
  // The bracket's own rounds, so a column header can read "Semifinal" or
  // "LB Final" rather than a bare depth.
  const roundShape = bracketRoundShape(type, encounters);

  const upperRounds = buildRoundGroups(
    encounters.filter((match) => match.round > 0 && !finalRoundNumbers.has(match.round))
  );
  const finalRounds = buildRoundGroups(
    isDE ? encounters.filter((match) => match.round > 0 && finalRoundNumbers.has(match.round)) : []
  );
  const lowerRounds = isDE ? buildRoundGroups(encounters.filter((match) => match.round < 0)) : [];

  // Main bracket columns (UB and LB); finals go in extra columns at the right.
  const mainColumns = Math.max(upperRounds.length, lowerRounds.length, 1);
  const totalColumns = mainColumns + finalRounds.length;
  const contentWidth = totalColumns * CARD_WIDTH + Math.max(totalColumns - 1, 0) * ROUND_GAP_X;
  const width = PADDING_X * 2 + contentWidth;

  const nodes: LayoutNode[] = [];
  const edges: LayoutEdge[] = [];
  const headers: LayoutHeader[] = [];

  const matchNumbers = computeMatchNumbers(upperRounds, lowerRounds, finalRounds);
  const slotHints = computeSlotHints(
    upperRounds,
    lowerRounds,
    finalRounds,
    matchNumbers,
    isDE,
    hasBracketConnections
  );
  // Team id → the encounter with its highest match number. Match numbers follow
  // play order across UB, LB and the finals, so "highest" is "newest".
  const latestMatchByTeam = new Map<number, number>();
  for (const match of encounters) {
    for (const teamId of [match.home_team_id, match.away_team_id]) {
      if (teamId <= 0) continue;
      const held = latestMatchByTeam.get(teamId);
      if (held === undefined || (matchNumbers.get(held) ?? 0) < (matchNumbers.get(match.id) ?? 0)) {
        latestMatchByTeam.set(teamId, match.id);
      }
    }
  }
  const columnX = (index: number) => PADDING_X + index * (CARD_WIDTH + ROUND_GAP_X);

  const upperBaseMatches = getRoundSectionMatchCapacity(upperRounds);
  const upperSectionHeight = sectionHeight(upperBaseMatches);
  const widestUpperRoundIndex = Math.max(
    0,
    upperRounds.findIndex((group) => group.matches.length === upperBaseMatches)
  );
  const upperHeaderY = PADDING_Y;
  const upperTop = upperHeaderY + HEADER_HEIGHT + HEADER_GAP_Y;

  upperRounds.forEach((group, columnIndex) => {
    // A play-in round narrower than the round after it sits half a pitch down,
    // so its cards land between the pairs they feed rather than centred over
    // the whole section.
    const isSparsePlayInRound =
      columnIndex < widestUpperRoundIndex && group.matches.length < upperBaseMatches;
    const startY =
      upperTop +
      (isSparsePlayInRound
        ? (CARD_HEIGHT + MATCH_GAP_Y) / 2
        : Math.max(0, (upperSectionHeight - sectionHeight(group.matches.length)) / 2));

    layoutColumn({
      group,
      x: columnX(columnIndex),
      headerY: upperHeaderY,
      headerId: `upper-header-${group.round}`,
      headerSection: "upper",
      label: roundLabel(group.round, roundShape),
      startY,
      slotHints,
      matchNumbers,
      latestMatchByTeam,
      headers,
      nodes
    });
  });

  const hasLowerBracket = lowerRounds.length > 0;
  const lowerHeaderY = upperTop + upperSectionHeight + (hasLowerBracket ? SECTION_GAP_Y : 0);
  const lowerTop = lowerHeaderY + HEADER_HEIGHT + HEADER_GAP_Y;
  const lowerSectionHeight = hasLowerBracket
    ? sectionHeight(getRoundSectionMatchCapacity(lowerRounds))
    : 0;

  lowerRounds.forEach((group, columnIndex) => {
    layoutColumn({
      group,
      x: columnX(columnIndex),
      headerY: lowerHeaderY,
      headerId: `lower-header-${group.round}`,
      headerSection: "lower",
      label: roundLabel(group.round, roundShape),
      startY: lowerTop + Math.max(0, (lowerSectionHeight - sectionHeight(group.matches.length)) / 2),
      slotHints,
      matchNumbers,
      latestMatchByTeam,
      headers,
      nodes
    });
  });

  // Grand Final section: right of both UB and LB, centred in the bracket body
  // — below the header row, or the card lands on top of its own header.
  const fullContentHeight = hasLowerBracket ? lowerTop + lowerSectionHeight : upperTop + upperSectionHeight;

  finalRounds.forEach((group, finalIndex) => {
    const totalHeight = sectionHeight(group.matches.length);
    layoutColumn({
      group,
      x: columnX(mainColumns + finalIndex),
      headerY: PADDING_Y,
      headerId: `final-header-${group.round}`,
      headerSection: "upper",
      label: roundLabel(group.round, roundShape),
      startY: upperTop + Math.max(0, (fullContentHeight - upperTop - totalHeight) / 2),
      slotHints,
      matchNumbers,
      latestMatchByTeam,
      headers,
      nodes
    });
  });

  const nodesById = new Map(nodes.map((node) => [node.id, node]));

  // Recorded advancement edges win; the column-index guesses below only fill in
  // the matches that carry none (a hand-created encounter, a legacy bracket).
  const wiredTargets = hasBracketConnections
    ? addWinnerSourceEdges(nodes, nodesById, edges)
    : new Set<number>();

  if (hasBracketConnections) {
    addSequentialEdges(upperRounds, nodesById, edges, wiredTargets, (matchIndex, targetCount) => {
      const targetIndex = Math.floor(matchIndex / 2);
      return targetIndex < targetCount ? targetIndex : -1;
    });
    addSequentialEdges(lowerRounds, nodesById, edges, wiredTargets, (matchIndex, targetCount) =>
      targetCount === 0 ? -1 : Math.min(matchIndex, targetCount - 1)
    );
  }

  if (isDE && finalRounds.length > 0) {
    const gfMatch = finalRounds[0].matches[0];
    const gfNode = gfMatch ? nodesById.get(`match-${gfMatch.id}`) : undefined;

    if (gfNode && gfMatch && !wiredTargets.has(gfMatch.id)) {
      for (const bracket of [upperRounds, lowerRounds]) {
        const finalMatch = bracket[bracket.length - 1]?.matches[0];
        const finalNode = finalMatch ? nodesById.get(`match-${finalMatch.id}`) : undefined;
        if (finalNode) edges.push(edgeBetween(finalNode, gfNode));
      }
    }

    // GF → GF Reset edge (if reset match exists).
    const gfrMatch = finalRounds[1]?.matches[0];
    const gfrNode = gfrMatch ? nodesById.get(`match-${gfrMatch.id}`) : undefined;
    if (gfNode && gfrNode) edges.push(edgeBetween(gfNode, gfrNode));
  }

  const height = fullContentHeight + PADDING_Y;

  return { nodes, edges, headers, width, height };
}
