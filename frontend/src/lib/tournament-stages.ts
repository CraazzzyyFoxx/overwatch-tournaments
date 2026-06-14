import type { Tournament } from "@/types/tournament.types";

export function formatTournamentStages(stages: Tournament["stages"]) {
  return stages
    .map((stage) => stage.name.trim())
    .filter(Boolean)
    .join(", ");
}
