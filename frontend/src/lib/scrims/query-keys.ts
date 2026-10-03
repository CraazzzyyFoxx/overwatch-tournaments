import type { KeyPart } from "@/lib/query-keys";

/** Keys for the scrim organizer: the tournament picker it copies a format from. */
export const scrimQueryKeys = {
  /** Rooms in one workspace, per list scope ("mine" or "workspace"). */
  list: (workspaceId: KeyPart, scope: KeyPart) => ["scrims", "list", workspaceId, scope] as const,
  /** A room addressed by its share token -- all an invited guest holds. */
  room: (token: KeyPart) => ["scrims", "room", token] as const,
  encounters: (tournamentId: KeyPart) => ["scrims", "encounters", tournamentId] as const,
  stages: (tournamentId: KeyPart) => ["scrims", "stages", tournamentId] as const,
  tournamentsLookup: (workspaceId: KeyPart) =>
    ["scrims", "tournaments-lookup", workspaceId] as const,
};
