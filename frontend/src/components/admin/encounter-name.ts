import type { Team } from "@/types/team.types";

type EncounterTeam = Pick<Team, "id" | "name">;

function getTeamName(teams: EncounterTeam[], teamId: number | null | undefined): string {
  const name = teams.find((team) => team.id === teamId)?.name.trim();
  return name || "TBD";
}

export function buildEncounterName(
  teams: EncounterTeam[],
  homeTeamId: number | null | undefined,
  awayTeamId: number | null | undefined
): string {
  return `${getTeamName(teams, homeTeamId)} vs ${getTeamName(teams, awayTeamId)}`;
}
