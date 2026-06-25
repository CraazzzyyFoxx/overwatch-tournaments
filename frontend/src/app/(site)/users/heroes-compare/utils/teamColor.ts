/**
 * Deterministic team-color derivation for the Hero Compare board.
 *
 * The leaderboard API returns a team name (and id) but no brand color, so we
 * derive a stable tint from the team identity. The same team always maps to the
 * same hue, which lets the small color-dot beside each player act as a
 * cross-column trace aid (mirrors the imported design mockup).
 */

const FALLBACK = "hsl(215 12% 30%)";

/** FNV-1a style string hash → stable non-negative integer. */
const hashString = (value: string): number => {
  let h = 2166136261;
  for (let i = 0; i < value.length; i++) {
    h ^= value.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
};

/** Stable hue (0–359) for a team key (name preferred, id as fallback). */
export const teamHue = (team: string | null | undefined, teamId?: number | null): number => {
  const key = team && team.trim() ? team : teamId != null ? `#${teamId}` : "";
  if (!key) return 0;
  return hashString(key) % 360;
};

/**
 * CSS background for a team dot — a diagonal gradient keyed to the team hue,
 * matching the mockup's tinted squares. Returns a neutral color when no team.
 */
export const teamDotBackground = (team: string | null | undefined, teamId?: number | null): string => {
  if (!team && teamId == null) return FALLBACK;
  const h = teamHue(team, teamId);
  return `linear-gradient(135deg, hsl(${h} 72% 62%), hsl(${h} 58% 36%))`;
};
