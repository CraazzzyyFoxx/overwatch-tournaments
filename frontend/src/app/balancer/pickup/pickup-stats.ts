import type { MixMemberStats } from "@/services/custom-game.service";

/**
 * The leaderboard's own arithmetic, apart from the component that renders it:
 * which window is being read, who is eligible to appear, and how a record
 * reads as one string. Nothing here touches the server -- the counting itself
 * is the endpoint's job.
 */

/** The windows a reader can put the record in, widest first. */
export const STATS_PERIODS = [
  { key: "all", label: "All time", days: null },
  { key: "30d", label: "30 days", days: 30 },
  { key: "7d", label: "7 days", days: 7 },
] as const;

export type StatsPeriodKey = (typeof STATS_PERIODS)[number]["key"];

/**
 * The `since` filter for a window, as a rolling span back from `now` rather
 * than a calendar boundary: "7 days" means the last seven days of play, not
 * "since Monday", so the number stops jumping at midnight.
 */
export function sinceFor(period: StatsPeriodKey, now: Date): string | null {
  const days = STATS_PERIODS.find((item) => item.key === period)?.days ?? null;
  return days == null ? null : new Date(now.getTime() - days * 86_400_000).toISOString();
}

/** Below this a record is noise — one lucky night would top the board. */
export const LEADERBOARD_MIN_GAMES = 3;

/**
 * The rows worth ranking. Server order is kept as-is: the endpoint already
 * sorted by wins, then win rate, then games, and re-sorting here would only
 * risk disagreeing with it.
 */
export function leaderboardRows(members: MixMemberStats[], minGames: number): MixMemberStats[] {
  return members.filter((member) => member.games >= minGames);
}

/** `W3`/`L2`, or nothing at all: a streak of zero is a state, not a badge. */
export function formatStreak(streak: number): string | null {
  if (streak === 0) return null;
  return streak > 0 ? `W${streak}` : `L${-streak}`;
}

/** Wins–losses, with draws appended only when there are any to report. */
export function formatRecord(member: MixMemberStats): string {
  const record = `${member.wins}–${member.losses}`;
  return member.draws > 0 ? `${record}–${member.draws}` : record;
}

/** The roster name if the member is still on it, their battletag if not, the raw id as a last resort. */
export function memberLabel(member: MixMemberStats): string {
  return member.display_name ?? member.battle_tag ?? `#${member.workspace_member_id}`;
}
