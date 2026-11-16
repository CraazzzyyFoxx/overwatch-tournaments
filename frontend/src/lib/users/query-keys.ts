import type { KeyPart } from "@/lib/query-keys";
import type { WorkspaceAxis } from "@/lib/site/discipline-scope";

/** The workspace dimension of a profile read: an id, or the public profile's `"all"` / `"workspace"` scope. */
type UserAxis = WorkspaceAxis | "workspace" | null | undefined;

/**
 * Keys for player-facing reads: the signed-in account (`me`), the user index and
 * its facets, a user's statistics in one game, the compare tool and rank history.
 *
 * A user's statistics share the §4.3 shape `["user-stats", userId, axis, discipline, family, ...filters]`, so a
 * catalog sync of one game drops them by the discipline position (`invalidateCatalogSync`). The index families are
 * `[family, axis, discipline, ...filters]` (§2.6).
 *
 * No user id in the `me` keys: the server resolves the account from the token,
 * and a per-user key would imply the cache could legitimately hold another
 * account's profile. They are cleared with the rest of the authenticated cache
 * on sign-out.
 */
export const userQueryKeys = {
  myDiscordGuilds: () => ["me", "discord-guilds"] as const,
  mySocial: () => ["me", "social"] as const,
  favoritePlayers: () => ["me", "favorite-players"] as const,
  rankHistory: (userId: KeyPart, params: unknown) =>
    ["rank-history", "user", userId, params] as const,
  rankCurrent: (userId: KeyPart, discipline: KeyPart) => ["rank-current", userId, discipline] as const,
  rankResolve: (battleTag: KeyPart) => ["rank-user-resolve", battleTag] as const,
  characterMaps: (userId: KeyPart, axis: UserAxis, discipline: string, tournamentId: KeyPart) =>
    ["user-stats", userId, axis, discipline, "character-maps", tournamentId] as const,
  characters: (userId: KeyPart, axis: UserAxis, discipline: string, tournamentId: KeyPart) =>
    ["user-stats", userId, axis, discipline, "characters", tournamentId] as const,
  mapsSummary: (userId: KeyPart, axis: UserAxis, discipline: string, filters: unknown) =>
    ["user-stats", userId, axis, discipline, "maps-summary", filters] as const,
  maps: (userId: KeyPart, axis: UserAxis, discipline: string, filters: unknown) =>
    ["user-stats", userId, axis, discipline, "maps", filters] as const,
  tournaments: (userId: KeyPart, axis: UserAxis, discipline: string) =>
    ["user-stats", userId, axis, discipline, "tournaments"] as const,
  /** One tournament's encounters of a user (the history dossier); the axis and game are that tournament's own. */
  tournamentEncounters: (userId: KeyPart, axis: UserAxis, discipline: string, tournamentId: KeyPart) =>
    ["user-stats", userId, axis, discipline, "tournament-encounters", tournamentId] as const,
  career: (userId: KeyPart, discipline: string) => ["user-stats", userId, null, discipline, "career"] as const,
  /** Prefix over every axis and game of one user's statistics — for invalidation, not for a read. */
  statsAll: (userId: KeyPart) => ["user-stats", userId] as const,
  overviewCatalog: (axis: UserAxis, discipline: string, query: KeyPart, role: KeyPart, divisions: KeyPart, hasLogs: KeyPart, letter: KeyPart) =>
    ["users-overview-catalog", axis, discipline, query, role, divisions, hasLogs, letter] as const,
  overviewStats: (axis: UserAxis, discipline: string, query: KeyPart, role: KeyPart, divisions: KeyPart, hasLogs: KeyPart) =>
    ["users-overview-stats", axis, discipline, query, role, divisions, hasLogs] as const,
  overview: (axis: UserAxis, discipline: string, page: KeyPart, perPage: KeyPart, query: KeyPart, sort: KeyPart, order: KeyPart, role: KeyPart, divisions: KeyPart, hasLogs: KeyPart, minEncounters: KeyPart) =>
    ["users-overview", axis, discipline, page, perPage, query, sort, order, role, divisions, hasLogs, minEncounters] as const,
  /** The index drawer's per-player career read in one game. */
  draftCard: (userId: KeyPart, axis: UserAxis, discipline: string) =>
    ["user-stats", userId, axis, discipline, "draft-card"] as const,
  compare: (subjectUserId: KeyPart, axis: UserAxis, discipline: string, filters: unknown) =>
    ["user-stats", subjectUserId, axis, discipline, "compare", filters] as const,
  characterCompare: (subjectUserId: KeyPart, axis: UserAxis, discipline: string, filters: unknown) =>
    ["user-stats", subjectUserId, axis, discipline, "character-compare", filters] as const
};
