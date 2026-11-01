import { Castle, Crown, Gem, Shield, ShieldHalf, type LucideIcon } from "lucide-react";

/** `CMsgLaneColor` -> its message key: the game's three lanes as its minimap paints them (left to right). */
export const LANE_KEY: Record<number, string> = { 1: "yellow", 4: "blue", 6: "green" };
/** `CMsgLaneColor` -> its swatch: a small diamond beside the lane's name, never a fill (amber and blue are side hues). */
export const LANE_COLOR: Record<number, string> = {
  1: "var(--aqt-amber)",
  4: "var(--aqt-blue)",
  6: "var(--aqt-emerald)"
};

export type ObjectiveKind = "core" | "guardian" | "walker" | "patron" | "shrine" | "baseGuardian";

/** `ECitadelTeamObjective` -> the structure and, for a lane structure, the lane's `CMsgLaneColor`. */
export function objectiveOf(id: number): { kind: ObjectiveKind; lane: number | null } {
  const lanes = [1, 3, 4, 6];
  if (id >= 1 && id <= 4) return { kind: "guardian", lane: lanes[id - 1] };
  if (id >= 5 && id <= 8) return { kind: "walker", lane: lanes[id - 5] };
  if (id === 9) return { kind: "patron", lane: null };
  if (id === 10 || id === 11) return { kind: "shrine", lane: null };
  if (id >= 12 && id <= 15) return { kind: "baseGuardian", lane: lanes[id - 12] };
  return { kind: "core", lane: null };
}

/** One glyph per structure, the same on the ribbon, its legend and the timeline. */
export const OBJECTIVE_ICON: Record<ObjectiveKind, LucideIcon> = {
  guardian: Shield,
  walker: Castle,
  baseGuardian: ShieldHalf,
  shrine: Gem,
  patron: Crown,
  core: Crown
};
