import teamService from "@/services/team.service";
import tournamentService from "@/services/tournament.service";
import type { Tournament } from "@/types/tournament.types";

export interface TournamentWinner {
  team: string;
  /** Full BattleTags of the winning roster, substitutes excluded. */
  players: string[];
}

export interface FinishedTournament {
  tournament: Tournament;
  /** `null` when the standings name no first place (yet). */
  winner: TournamentWinner | null;
}

/**
 * The newest completed tournaments, each with its champion — the "last
 * tournament" and chronicle blocks of the home and community pages.
 *
 * There is no "tournaments with winners" read, so the champion comes off the
 * teams read with `placement` (the same source the tournament overview's
 * podium uses), one request per tournament. `workspaceId` is passed through to
 * the teams read explicitly: left empty, `apiFetch` would scope it to the
 * viewer's current workspace and drop another community's teams.
 */
export async function getFinishedTournaments({
  workspaceId,
  limit
}: Readonly<{ workspaceId: number | "all"; limit: number }>): Promise<FinishedTournament[]> {
  const page = await tournamentService.listTournaments({
    workspaceId,
    status: "completed",
    sort: "start_date",
    order: "desc",
    perPage: limit
  });

  return Promise.all(
    page.results.map(async (tournament) => {
      const teams = await teamService.getAll({
        tournamentId: tournament.id,
        workspaceId: tournament.workspace_id,
        sort: "placement",
        order: "asc"
      });
      const champion = teams.results.find((team) => team.placement === 1);
      return {
        tournament,
        winner: champion
          ? {
              team: champion.name,
              players: champion.players
                .filter((player) => !player.is_substitution)
                .map((player) => player.name)
            }
          : null
      };
    })
  );
}
