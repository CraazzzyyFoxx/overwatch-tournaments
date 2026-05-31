import type { UserTournamentSummary } from "@/types/user.types";
import type { DivisionGridVersion } from "@/types/workspace.types";

export function getLastTournamentGridVersion(
  tournamentId: number,
  tournaments: UserTournamentSummary[]
): DivisionGridVersion | null {
  return tournaments.find((tournament) => tournament.id === tournamentId)?.division_grid_version ?? null;
}
