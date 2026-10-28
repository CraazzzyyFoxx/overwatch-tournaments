"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { useAuthProfile } from "@/hooks/useAuthProfile";
import { tournamentTeamsQueryOptions } from "@/lib/tournament/teams-query";
import type { Player, Team } from "@/types/team.types";
import type { Tournament } from "@/types/tournament.types";

export interface RosterEntry {
  player: Player;
  team: Team;
}

export interface TournamentRoster {
  teams: Team[];
  byUser: Map<number, RosterEntry>;
  byPlayer: Map<number, RosterEntry>;
  byTeam: Map<number, Team>;
}

/** The tournament's teams (the Teams tab's own cache entry), indexed by user, tournament player and team. */
export function useTournamentRoster(
  tournament: Pick<Tournament, "id" | "workspace_id">
): TournamentRoster {
  const query = useQuery(tournamentTeamsQueryOptions(tournament));
  return useMemo(() => {
    const teams = query.data?.results ?? [];
    const byUser = new Map<number, RosterEntry>();
    const byPlayer = new Map<number, RosterEntry>();
    const byTeam = new Map<number, Team>();
    for (const team of teams) {
      byTeam.set(team.id, team);
      for (const player of team.players) {
        byUser.set(player.user_id, { player, team });
        byPlayer.set(player.id, { player, team });
      }
    }
    return { teams, byUser, byPlayer, byTeam };
  }, [query.data]);
}

/** The signed-in viewer's player among the ids `known` counts as participants on this screen, or `null`. */
export function useViewerUserId(known: (userId: number) => boolean): number | null {
  const { user } = useAuthProfile();
  return user?.linkedPlayers.map((linked) => linked.playerId).find(known) ?? null;
}
