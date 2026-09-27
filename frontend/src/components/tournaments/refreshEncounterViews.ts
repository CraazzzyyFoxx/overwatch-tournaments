import type { QueryClient } from "@tanstack/react-query";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";

/**
 * Invalidates every cached view that shows an encounter's score/status —
 * shared by the admin edit dialog and the captain match report form, which
 * both write to the same encounter and need the same views to refetch.
 */
export async function refreshEncounterViews(qc: QueryClient, tournamentId: number): Promise<void> {
  await Promise.all([
    qc.invalidateQueries({ queryKey: encounterQueryKeys.all() }),
    qc.invalidateQueries({ queryKey: tournamentQueryKeys.standings(tournamentId) }),
    qc.invalidateQueries({ queryKey: tournamentQueryKeys.detailRoot() }),
    qc.invalidateQueries({ queryKey: encounterQueryKeys.detailRoot() }),
    qc.invalidateQueries({ queryKey: encounterQueryKeys.bracket() })
  ]);
}
