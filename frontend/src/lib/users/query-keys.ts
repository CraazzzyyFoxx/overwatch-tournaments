import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for player-facing reads: the signed-in account (`me`), the user index and
 * its facets, a user's hero/map breakdowns, the compare tool and rank history.
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
  rankResolve: (battleTag: KeyPart) => ["rank-user-resolve", battleTag] as const,
  heroMaps: (userId: KeyPart, tournamentId: KeyPart) =>
    ["user-heroes-maps", userId, tournamentId] as const,
  heroes: (userId: KeyPart, tournamentId: KeyPart) =>
    ["user-heroes", userId, tournamentId] as const,
  mapsSummary: (userId: KeyPart, query: KeyPart, minCount: KeyPart, tournamentId: KeyPart) =>
    ["user-maps-summary", userId, query, minCount, tournamentId] as const,
  maps: (userId: KeyPart, query: KeyPart, minCount: KeyPart, tournamentId: KeyPart) =>
    ["user-maps", userId, query, minCount, tournamentId] as const,
  tournaments: (userId: KeyPart, workspaceId: KeyPart) =>
    ["user-tournaments", userId, workspaceId] as const,
  tournamentsAll: (userId: KeyPart) => ["user-tournaments", userId] as const,
  overviewCatalog: (workspaceId: KeyPart, query: KeyPart, role: KeyPart, divMin: KeyPart, divMax: KeyPart, letter: KeyPart) =>
    ["users-overview-catalog", workspaceId, query, role, divMin, divMax, letter] as const,
  overviewStats: (workspaceId: KeyPart, query: KeyPart, role: KeyPart, divMin: KeyPart, divMax: KeyPart) =>
    ["users-overview-stats", workspaceId, query, role, divMin, divMax] as const,
  overview: (workspaceId: KeyPart, page: KeyPart, perPage: KeyPart, query: KeyPart, sort: KeyPart, order: KeyPart, role: KeyPart, divMin: KeyPart, divMax: KeyPart) =>
    ["users-overview", workspaceId, page, perPage, query, sort, order, role, divMin, divMax] as const,
  searchMinimized: (query: KeyPart) => ["users-search-minimized", query] as const,
  compare: (subjectUserId: KeyPart, baseline: KeyPart, targetUserId: KeyPart, role: KeyPart, divMin: KeyPart, divMax: KeyPart, tournamentId: KeyPart) =>
    ["user-compare", subjectUserId, baseline, targetUserId, role, divMin, divMax, tournamentId] as const,
  heroCompare: (subjectUserId: KeyPart, baseline: KeyPart, targetUserId: KeyPart, role: KeyPart, divMin: KeyPart, divMax: KeyPart, tournamentId: KeyPart, leftHeroId: KeyPart, rightHeroId: KeyPart, mapId: KeyPart) =>
    ["user-hero-compare", subjectUserId, baseline, targetUserId, role, divMin, divMax, tournamentId, leftHeroId, rightHeroId, mapId] as const,
};
