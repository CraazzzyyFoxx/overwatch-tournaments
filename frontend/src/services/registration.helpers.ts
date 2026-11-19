import type { DivisionGridVersion } from "@/types/workspace.types";
import type {
  Registration,
  RegistrationListResponse,
  TournamentHistoryEntry,
} from "@/types/registration.types";

/**
 * Rehydrate the deduplicated division grid versions from a list envelope back
 * onto each tournament-history entry (by reference).
 *
 * The backend dedups grid versions into `division_grids` (keyed by version id, as
 * JSON object keys these arrive as strings) and references them from each entry
 * via `division_grid_version_id`, keeping the payload small. Both the public
 * participants list and the admin registrations list use this envelope.
 */
export function rehydrateHistoryGrids<T extends { tournament_history?: TournamentHistoryEntry[] }>(
  rows: T[],
  grids: Record<string, DivisionGridVersion> | undefined,
): T[] {
  const byId = grids ?? {};
  return rows.map((row) => ({
    ...row,
    tournament_history: (row.tournament_history ?? []).map((entry) => ({
      ...entry,
      division_grid_version:
        entry.division_grid_version_id != null
          ? (byId[String(entry.division_grid_version_id)] ?? null)
          : null,
    })),
  }));
}

/** The public participants envelope as a flat `Registration[]`, grids rehydrated. */
export function rehydrateRegistrationList(
  data: RegistrationListResponse,
): Registration[] {
  return rehydrateHistoryGrids(data.registrations ?? [], data.division_grids);
}
