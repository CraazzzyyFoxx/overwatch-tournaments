import type { KeyPart } from "@/lib/query-keys";

/** Room lists, token details and source-tournament lookups. */
export const scrimQueryKeys = {
  lists: (workspaceId: KeyPart) => ["scrims", "list", workspaceId] as const,
  /** Rooms in one workspace, per list scope ("mine" or "workspace"). */
  list: (workspaceId: KeyPart, scope: KeyPart) => ["scrims", "list", workspaceId, scope] as const,
  /** A room addressed by its share token -- all an invited guest holds. */
  room: (token: KeyPart) => ["scrims", "room", token] as const,
  encounters: (tournamentId: KeyPart) => ["scrims", "encounters", tournamentId] as const,
  stages: (tournamentId: KeyPart) => ["scrims", "stages", tournamentId] as const,
  tournamentsLookup: (workspaceId: KeyPart) =>
    ["scrims", "tournaments-lookup", workspaceId] as const,
};
