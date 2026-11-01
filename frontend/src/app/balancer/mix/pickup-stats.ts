import type { MixMemberStats, MixOutcome, MixRoleTally, MixStatsResponse } from "@/services/custom-game.service";
import type { PersonDisplay } from "@/types/user.types";

/**
 * The scoreboard's own arithmetic, apart from the components that render it:
 * which window is being read, how one person's records from several
 * communities become one row, and how a record reads as one string. The
 * counting itself is the endpoint's job; only the cross-community join is
 * done here, because each community is read on its own.
 */

/** The windows a reader can put the record in, widest first. */
export const STATS_PERIODS = [
  { key: "all", days: null },
  { key: "30d", days: 30 },
  { key: "7d", days: 7 },
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

/** The server sends at most this many results per member; a merged form keeps the same window. */
const FORM_LIMIT = 10;

/** One person on the scoreboard: a player's records from every community read, added up. */
export type RatedPlayer = {
  /** `p:<player id>`, or `m:<workspace>:<member>` for a member who can no longer be resolved to a player. */
  key: string;
  playerId: number | null;
  /** The name from the community they played most in: the game name on a single-game read, canonical on "all games". */
  display: PersonDisplay;
  games: number;
  wins: number;
  losses: number;
  draws: number;
  /** `wins / games` as a share. */
  winRate: number;
  /** `+n` wins / `-n` losses in a row from the newest match, 0 after a draw. */
  streak: number;
  /** The run fills the whole merged form window: it is at least `streak` long, maybe longer. */
  streakOpen: boolean;
  /** Newest first, at most `FORM_LIMIT`. */
  form: MixOutcome[];
  lastPlayedAt: string | null;
  /** Summed per-role split; `null` across games, where role codes of different games are different roles. */
  byRole: Record<string, MixRoleTally> | null;
};

export type StatsSource = { workspaceId: number; stats: MixStatsResponse };

function run(form: readonly MixOutcome[]): number {
  const newest = form[0];
  if (newest === undefined || newest === "draw") return 0;
  let length = 0;
  while (length < form.length && form[length] === newest) length += 1;
  return newest === "win" ? length : -length;
}

function addRoles(
  into: Record<string, MixRoleTally> | null,
  from: Record<string, MixRoleTally> | null
): Record<string, MixRoleTally> | null {
  if (into === null || from === null) return into ?? from;
  const out = { ...into };
  for (const [role, tally] of Object.entries(from)) {
    const known = out[role];
    out[role] = known
      ? {
          games: known.games + tally.games,
          wins: known.wins + tally.wins,
          losses: known.losses + tally.losses,
          draws: known.draws + tally.draws,
        }
      : tally;
  }
  return out;
}

/**
 * Every community's scoreboard joined into one, best record first.
 *
 * Members are joined by `player_id`: a membership is per community, the player
 * behind it is global. Totals add up; the form is the newest `FORM_LIMIT`
 * results across all of them, by when each was recorded (match ids only break a
 * tie: a match's id is fixed when it starts). A one-community player keeps the server's exact
 * form and streak; a joined one counts it from the merged form, which is exact unless
 * the run fills the whole window -- then it is only known to be at least that
 * long (`streakOpen`).
 */
export function mergeMixStats(sources: readonly StatsSource[]): RatedPlayer[] {
  const groups = new Map<string, MixMemberStats[]>();
  for (const { workspaceId, stats } of sources) {
    for (const member of stats.members) {
      const key =
        member.player_id != null ? `p:${member.player_id}` : `m:${workspaceId}:${member.workspace_member_id}`;
      const group = groups.get(key);
      if (group) group.push(member);
      else groups.set(key, [member]);
    }
  }

  const players: RatedPlayer[] = [];
  for (const [key, members] of groups) {
    const byGames = [...members].sort((a, b) => b.games - a.games);
    const games = members.reduce((sum, member) => sum + member.games, 0);
    const wins = members.reduce((sum, member) => sum + member.wins, 0);
    const single = members.length === 1;
    // One community's form is already in the server's exact recording order; only a merge re-sorts.
    // ponytail: Date.parse keeps milliseconds, so two communities' results recorded in the same millisecond fall
    // back to match id (Start order); send a server-side sort key if that ever matters.
    const entries = (
      single
        ? members[0].form
        : members
            .flatMap((member) => member.form)
            .sort((a, b) => Date.parse(b.recorded_at) - Date.parse(a.recorded_at) || b.match_id - a.match_id)
    ).slice(0, FORM_LIMIT);
    const form = entries.map((entry) => entry.outcome);
    const streak = single ? members[0].streak : run(form);
    players.push({
      key,
      playerId: members[0].player_id,
      display: byGames[0].display,
      games,
      wins,
      losses: members.reduce((sum, member) => sum + member.losses, 0),
      draws: members.reduce((sum, member) => sum + member.draws, 0),
      winRate: games > 0 ? wins / games : 0,
      streak,
      streakOpen: !single && Math.abs(streak) === FORM_LIMIT && games > FORM_LIMIT,
      form,
      lastPlayedAt: entries[0]?.played_at ?? byGames[0].last_played_at,
      byRole: members.reduce<Record<string, MixRoleTally> | null>((roles, member) => addRoles(roles, member.by_role), null),
    });
  }

  // The server's own order: most wins, then the better win rate, then the bigger sample, then a stable key.
  return players.sort(
    (a, b) => b.wins - a.wins || b.winRate - a.winRate || b.games - a.games || a.key.localeCompare(b.key)
  );
}

/** `W3`/`L2`, `W10+` for a run longer than the window shows, or nothing at all: a streak of zero is a state. */
export function formatStreak(streak: number, open = false): string | null {
  if (streak === 0) return null;
  return `${streak > 0 ? "W" : "L"}${Math.abs(streak)}${open ? "+" : ""}`;
}

/** Wins–losses, with draws appended only when there are any to report. */
export function formatRecord(member: Pick<MixMemberStats, "wins" | "losses" | "draws">): string {
  const record = `${member.wins}–${member.losses}`;
  return member.draws > 0 ? `${record}–${member.draws}` : record;
}
