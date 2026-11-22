import type { StreamEntry, TournamentStreams } from "@/types/stream.types";

/**
 * Team id → the participant stream that speaks for that team right now.
 *
 * Its own module rather than a function in `bracketData.ts`: that file pulls in
 * the encounter and tournament services to assemble query plans, and none of
 * that is needed to answer "who from this team is on air". Keeping the reduction
 * import-free is what makes it testable without a render or a query client.
 *
 * The key is `StreamTeam.id` — the tournament team id, the same value
 * `EncounterTeam.team_id` carries — so a bracket slot looks itself
 * up directly with no second mapping in between.
 */
export function buildLiveTeamStreams(
  streams: TournamentStreams | undefined
): ReadonlyMap<number, StreamEntry> {
  const byTeam = new Map<number, StreamEntry>();
  if (!streams) return byTeam;

  // `streams.official` is deliberately never consulted. A caster's channel
  // belongs to the broadcast, not to either side of the match, so attributing it
  // to a team would light up bracket slots while nobody on them is streaming.
  for (const entry of streams.participants) {
    // No team is an ordinary state, not bad data: a player can stream during
    // check-in, long before the balancer forms rosters.
    const teamId = entry.player?.team?.id;
    if (teamId == null) continue;

    const incumbent = byTeam.get(teamId);
    if (incumbent === undefined || outranksForTeam(entry, incumbent)) {
      byTeam.set(teamId, entry);
    }
  }

  return byTeam;
}

/**
 * The stream that speaks for a set of players (an individual-Swiss seat), picked
 * by the same rule as `buildLiveTeamStreams`. Those teams are per-round seats
 * with no tournament team id, so the join is `StreamEntry.player.id` (the user
 * id) against each seat member's `player_id`.
 */
export function liveStreamForPlayers(
  streams: TournamentStreams | undefined,
  playerIds: ReadonlySet<number>
): StreamEntry | undefined {
  let best: StreamEntry | undefined;
  for (const entry of streams?.participants ?? []) {
    if (entry.player == null || !playerIds.has(entry.player.id)) continue;
    if (best === undefined || outranksForTeam(entry, best)) best = entry;
  }
  return best;
}

/**
 * Which of two streams from the same team the bracket names. Audience first,
 * then `channel` as a total order.
 *
 * The tie-break is not cosmetic: the bracket refetches every 15s while a
 * tournament is live, and a comparison that fell through to arrival order would
 * swap the named player back and forth between two equally-watched streams on
 * every poll.
 */
function outranksForTeam(candidate: StreamEntry, incumbent: StreamEntry): boolean {
  const left = candidate.viewer_count;
  const right = incumbent.viewer_count;

  if (left !== right) {
    // `null` means the platform reports no count at all, not zero viewers, so it
    // must never displace a channel that has a real number behind it.
    if (left == null) return false;
    if (right == null) return true;
    return left > right;
  }

  return candidate.channel < incumbent.channel;
}
