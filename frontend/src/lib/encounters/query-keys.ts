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
  /** The past broadcasts that cover the encounter (`/streams/encounter/{id}/vods`). */
  vods: (encounterId: KeyPart) => ["encounter", encounterId, "vods"] as const,
  /** One game's index and its tournament picker (§2.6): `discipline` sits right after the workspace axis. */
  list: (workspaceId: KeyPart, discipline: KeyPart, page: KeyPart, filters: unknown, query: KeyPart) =>
    ["encounters-list", workspaceId, discipline, page, filters, query] as const,
  overview: (workspaceId: KeyPart, discipline: KeyPart, filters: unknown, query: KeyPart) =>
    ["encounters-overview", workspaceId, discipline, filters, query] as const,
  insights: (workspaceId: KeyPart, discipline: KeyPart, filters: unknown, query: KeyPart) =>
    ["encounters-insights", workspaceId, discipline, filters, query] as const,
  savedViews: (workspaceId: KeyPart, userKey: KeyPart) =>
    ["encounters-saved-views", workspaceId, userKey] as const,
  tournamentsLookup: (workspaceId: KeyPart, discipline: KeyPart) =>
    ["encounters-tournaments-lookup", workspaceId, discipline] as const,
  byTournament: (tournamentId: KeyPart) => ["encounters", "by-tournament", tournamentId] as const,
  all: () => ["encounters"] as const,
  matchDetail: (matchId: KeyPart) => ["match-detail", matchId] as const,
  /** One match's native event timeline (`/matches/{id}/kill-feed`), read when a timeline is opened. */
  matchEvents: (matchId: KeyPart) => ["match-events", matchId] as const,
  pregameHeroState: (encounterId: KeyPart) => ["pregame-state", encounterId, "hero"] as const,
  pregameMapState: (encounterId: KeyPart) => ["pregame-state", encounterId, "map"] as const,
  /** The organizer's room journal, only read while the history panel is open. */
  roomHistory: (encounterId: KeyPart) => ["encounter", encounterId, "room-history"] as const,
  pregameState: (encounterId: KeyPart, kind: KeyPart) =>
    ["pregame-state", encounterId, kind] as const,
  /** One game's match imports; the organizer read (`admin`) adds the warnings a captain does not see. */
  matchImports: (encounterId: KeyPart, gameId: KeyPart, admin: boolean) =>
    ["encounter", encounterId, "match-imports", gameId, admin ? "admin" : "captain"] as const,
  /** Every game's match imports of one encounter, both reads: what an observation written for it stales. */
  matchImportsOf: (encounterId: KeyPart) => ["encounter", encounterId, "match-imports"] as const,
  bracket: () => ["bracket"] as const,
};
