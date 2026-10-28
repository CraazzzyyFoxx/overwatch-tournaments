import { queryOptions } from "@tanstack/react-query";

import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";
import tournamentService from "@/services/tournament.service";
import type { DraftBoard } from "@/types/draft.types";
import type {
  PickBanOutcomesResponse,
  Tournament,
  TournamentPlayerStatKey,
  TournamentPlayerStatsResponse,
  TournamentStatus
} from "@/types/tournament.types";

/** The ranked stats, in the order the statistics table shows them. */
export const PLAYER_STATS: readonly TournamentPlayerStatKey[] = [
  "performance",
  "kda",
  "eliminations",
  "deaths",
  "assists",
  "hero_damage_dealt",
  "damage_delta"
];

export type PlayerStat = { value: number; rank: number };

/** One team's choice to ban a hero; `targetPlayerId` names the opponent it was aimed at (maps after the first). */
export type HeroBan = {
  encounterId: number;
  heroId: number;
  firstMap: boolean;
  targetPlayerId: number | null;
};
/** One map struck from (or chosen out of) a series' pool. */
export type MapBan = { encounterId: number; mapId: number; picked: boolean };

/** A pick slot of the draft: who picks, when, for which role. */
export type DraftSlot = {
  overall: number;
  round: number;
  inRound: number;
  /** The tournament team the draft team became. */
  teamId: number | null;
  role: string | null;
};

/** A made pick. */
export type DraftEntry = DraftSlot & {
  userId: number | null;
  name: string;
  rank: number | null;
  autopick: boolean;
  /** When the pick was made: the next pick's clock start (the last pick: its own). ISO. */
  at: string | null;
};

export type DraftPlayer = {
  userId: number | null;
  name: string;
  role: string | null;
  rank: number | null;
};

export type TournamentDraft = {
  rounds: number;
  /** Made picks, in pick order. */
  picks: DraftEntry[];
  /** The pick on the clock, `null` once the draft is over (or paused between picks). */
  onClock: DraftSlot | null;
  /** Picks not made yet, in pick order (the one on the clock included). */
  upcoming: DraftSlot[];
  captains: (DraftPlayer & { teamId: number | null; position: number })[];
  /** Everyone in the pool who is not a captain. */
  pool: DraftPlayer[];
};

export type TournamentInsights = {
  /** user id -> stat -> value and rank among the tournament's players. */
  players: Record<number, Partial<Record<TournamentPlayerStatKey, PlayerStat>>>;
  playersTotal: number;
  heroBans: HeroBan[];
  mapBans: MapBan[];
  draft: TournamentDraft | null;
};

export function mapPlayerStats(
  response: TournamentPlayerStatsResponse
): Pick<TournamentInsights, "players" | "playersTotal"> {
  const players: TournamentInsights["players"] = {};
  for (const row of response.players) players[row.player_id] = row.stats;
  return { players, playersTotal: response.total_players };
}

export function mapPickBanOutcomes(
  response: PickBanOutcomesResponse
): Pick<TournamentInsights, "heroBans" | "mapBans"> {
  return {
    heroBans: response.hero_bans.map((ban) => ({
      encounterId: ban.encounter_id,
      heroId: ban.hero_id,
      firstMap: ban.first_map,
      targetPlayerId: ban.target_player_id
    })),
    mapBans: response.map_outcomes.map((row) => ({
      encounterId: row.encounter_id,
      mapId: row.map_id,
      picked: row.picked
    }))
  };
}

/** The draft board as the tournament pages read it; `null` when there is no draft or no pick to show. */
export function mapDraftBoard(board: DraftBoard | null): TournamentDraft | null {
  if (!board || board.picks.length === 0) return null;
  const teamOf = new Map(board.teams.map((team) => [team.id, team]));
  const playerOf = new Map(board.players.map((player) => [player.id, player]));
  const ordered = [...board.picks].sort((a, b) => a.overall_no - b.overall_no);
  const slot = (pick: DraftBoard["picks"][number]): DraftSlot => ({
    overall: pick.overall_no,
    round: pick.round_no,
    inRound: pick.pick_in_round,
    teamId: teamOf.get(pick.draft_team_id)?.exported_team_id ?? null,
    role: pick.target_role?.role ?? null
  });
  const made = ordered.filter((pick) => pick.picked_player_id != null);
  const picks = made.map((pick, index): DraftEntry => {
    const player = playerOf.get(pick.picked_player_id as number);
    return {
      ...slot(pick),
      userId: player?.user_id ?? null,
      name: player?.player_name ?? player?.identity?.handle ?? "—",
      role: pick.target_role?.role ?? player?.primary_role?.role ?? null,
      rank: player?.effective_rank ?? null,
      autopick: pick.is_autopick,
      at: made[index + 1]?.clock_started_at ?? pick.clock_started_at
    };
  });
  const captains = board.teams
    .map((team) => {
      const player = board.players.find((p) => p.is_captain && p.user_id === team.captain_user_id);
      return {
        position: team.draft_position,
        teamId: team.exported_team_id,
        userId: team.captain_user_id,
        name: player?.player_name ?? team.name,
        role: player?.captain_role?.role ?? player?.primary_role?.role ?? null,
        rank: player?.effective_rank ?? null
      };
    })
    .sort((a, b) => a.position - b.position);
  const pool = board.players
    .filter((player) => !player.is_captain)
    .map((player) => ({
      userId: player.user_id,
      name: player.player_name ?? player.identity?.handle ?? "—",
      role: player.primary_role?.role ?? null,
      rank: player.effective_rank
    }));
  return {
    rounds: board.session.rounds,
    picks,
    onClock: board.current_pick ? slot(board.current_pick) : null,
    upcoming: ordered.filter((pick) => pick.picked_player_id == null).map(slot),
    captains,
    pool
  };
}

const LIVE_REFETCH_MS = 30_000;
const FINISHED_STALE_MS = 60 * 60_000;

/** Live phases poll; a finished tournament's numbers no longer move. */
function freshness(status: TournamentStatus, live: readonly TournamentStatus[]) {
  return live.includes(status)
    ? { refetchInterval: LIVE_REFETCH_MS, refetchIntervalInBackground: false }
    : { staleTime: status === "completed" || status === "archived" ? FINISHED_STALE_MS : 0 };
}

// A view without these numbers shows its empty state; an error toast would only repeat it.
const QUIET = { suppressErrorToast: true };

const PLAYING: readonly TournamentStatus[] = ["draft", "live", "playoffs"];

export function tournamentPlayerStatsQueryOptions(tournament: Pick<Tournament, "id" | "status">) {
  return queryOptions({
    queryKey: tournamentQueryKeys.playerStats(tournament.id),
    queryFn: () => tournamentService.getPlayerStats(tournament.id),
    select: mapPlayerStats,
    meta: QUIET,
    ...freshness(tournament.status, PLAYING)
  });
}

export function tournamentPickBanOutcomesQueryOptions(
  tournament: Pick<Tournament, "id" | "status">
) {
  return queryOptions({
    queryKey: tournamentQueryKeys.pickBanOutcomes(tournament.id),
    queryFn: () => tournamentService.getPickBanOutcomes(tournament.id),
    select: mapPickBanOutcomes,
    meta: QUIET,
    ...freshness(tournament.status, PLAYING)
  });
}

/** The draft board under the draft room's own key, refetched while the captains draft. */
export function tournamentDraftQueryOptions(tournament: Pick<Tournament, "id" | "status">) {
  return queryOptions({
    queryKey: tournamentQueryKeys.draftBoard(tournament.id),
    queryFn: () => draftService.getTournamentBoard(tournament.id),
    select: mapDraftBoard,
    meta: QUIET,
    ...freshness(tournament.status, ["draft"])
  });
}
