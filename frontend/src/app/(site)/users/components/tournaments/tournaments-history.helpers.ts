import type { UserTournament } from "@/types/user.types";

/** League grouping key: the prefix before " | " in the tournament name. */
export const leagueKey = (t: UserTournament): string => t.name.split(" | ")[0];

export type TournamentGroup = UserTournament | UserTournament[];

/**
 * Group consecutive league tournaments (those with `is_league` sharing the same
 * league-name prefix) into arrays; non-league tournaments remain standalone
 * entries. Input order is preserved, so a league's divisions stay contiguous
 * exactly as the API returns them.
 */
export const groupTournamentsByLeague = (tournaments: UserTournament[]): TournamentGroup[] => {
  const result: TournamentGroup[] = [];
  let currentLeague: UserTournament[] = [];
  let flag = "";

  tournaments.forEach((t) => {
    if (t.is_league) {
      const key = leagueKey(t);
      if (flag && flag !== key) {
        result.push(currentLeague);
        currentLeague = [];
      }
      flag = key;
      currentLeague.push(t);
    } else {
      if (currentLeague.length > 0) {
        result.push(currentLeague);
        currentLeague = [];
        flag = "";
      }
      result.push(t);
    }
  });

  if (currentLeague.length > 0) result.push(currentLeague);

  return result;
};
