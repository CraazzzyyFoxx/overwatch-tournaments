import type {
  Registration,
  RegistrationListResponse,
} from "@/types/registration.types";

/**
 * Rehydrate the deduplicated division grid versions from the list envelope back
 * onto each tournament-history entry (by reference), returning a flat
 * `Registration[]` so downstream components keep working unchanged.
 *
 * The backend dedups grid versions into `division_grids` (keyed by version id, as
 * JSON object keys these arrive as strings) and references them from each entry
 * via `division_grid_version_id`, keeping the payload small.
 */
export function rehydrateRegistrationList(
  data: RegistrationListResponse,
): Registration[] {
  const grids = data.division_grids ?? {};
  return (data.registrations ?? []).map((reg) => ({
    ...reg,
    tournament_history: (reg.tournament_history ?? []).map((entry) => ({
      ...entry,
      division_grid_version:
        entry.division_grid_version_id != null
          ? (grids[String(entry.division_grid_version_id)] ?? null)
          : null,
    })),
  }));
}
