import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for encounters: the public list and detail, captain reports, the pregame
 * pick/ban sessions and the parsed-match views behind them.
 *
 * Tournament-scoped encounter collections (`["encounters", "tournament", id]`)
 * stay in `lib/tournament/query-keys.ts` -- they are invalidated by tournament
 * writes, not by a single encounter's.
 */
export const encounterQueryKeys = {
  detail: (encounterId: KeyPart) => ["encounter-detail", encounterId] as const,
  reportsByEncounter: (encounterId: KeyPart, workspaceId: KeyPart) =>
    ["encounter-reports", "encounter", encounterId, workspaceId] as const,
  reportStats: (params: unknown) => ["encounter-reports", "stats", params] as const,
  reports: (encounterId: KeyPart) => ["encounter-reports", encounterId] as const,
  reportsAll: () => ["encounter-reports"] as const,
  resultAudit: (encounterId: KeyPart) => ["encounter-result-audit", encounterId] as const,
  myRole: (encounterId: KeyPart) => ["encounter", encounterId, "my-role"] as const,
  mapPickBanState: (encounterId: KeyPart) =>
    ["encounter", encounterId, "pick-ban-state", "map"] as const,
  captainReports: (encounterId: KeyPart) => ["encounter", encounterId, "reports"] as const,
  detailRoot: () => ["encounter"] as const,
  list: (workspaceId: KeyPart, page: KeyPart, filters: unknown, query: KeyPart) =>
    ["encounters-list", workspaceId, page, filters, query] as const,
  overview: (workspaceId: KeyPart, filters: unknown, query: KeyPart) =>
    ["encounters-overview", workspaceId, filters, query] as const,
  savedViews: (workspaceId: KeyPart, userKey: KeyPart) =>
    ["encounters-saved-views", workspaceId, userKey] as const,
  tournamentsLookup: (workspaceId: KeyPart) =>
    ["encounters-tournaments-lookup", workspaceId] as const,
  byTournament: (tournamentId: KeyPart) => ["encounters", "by-tournament", tournamentId] as const,
  all: () => ["encounters"] as const,
  matchDetail: (matchId: KeyPart) => ["match-detail", matchId] as const,
  pregameHeroState: (encounterId: KeyPart) => ["pregame-state", encounterId, "hero"] as const,
  pregameMapState: (encounterId: KeyPart) => ["pregame-state", encounterId, "map"] as const,
  /** The organizer's room journal, only read while the history panel is open. */
  roomHistory: (encounterId: KeyPart) => ["encounter", encounterId, "room-history"] as const,
  pregameState: (encounterId: KeyPart, kind: KeyPart) =>
    ["pregame-state", encounterId, kind] as const,
  bracket: () => ["bracket"] as const,
};
