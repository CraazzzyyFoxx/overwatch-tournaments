import type { DivisionGridVersion } from "@/types/workspace.types";

type TournamentWithDivisionGrid = {
  division_grid_version?: DivisionGridVersion | null;
} | null | undefined;

type TeamWithTournament = {
  tournament?: TournamentWithDivisionGrid;
} | null | undefined;

export function getPlayerRowDivisionGrid(team: TeamWithTournament): DivisionGridVersion | null {
  return team?.tournament?.division_grid_version ?? null;
}
