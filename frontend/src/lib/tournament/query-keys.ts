import type { KeyPart } from "@/lib/query-keys";

export const tournamentQueryKeys = {
  // `ref` is either the resolved numeric tournament id (admin flow, and
  // every other key in this object) or the public `/tournaments/{ref}` URL
  // segment (slug / legacy numeric id / retired slug) -- the public overview
  // query stays keyed by that ref for its whole lifecycle; realtime
  // invalidation targets it via the same ref (`ResourceKeyContext.detailRef`),
  // never the resolved numeric id.
  detail: (ref: string | number) => ["tournament", ref] as const,
  stages: (tournamentId: number) => ["tournament", tournamentId, "stages"] as const,
  streams: (tournamentId: number) => ["tournament", tournamentId, "streams"] as const,
  links: (tournamentId: number) => ["tournament", tournamentId, "links"] as const,
  /** `tournamentId` is nullable here: the admin browsers key this list by the
   *  scope chip, and "no tournament picked" is its own cache entry. */
  teams: (tournamentId: KeyPart, workspaceId?: number | null) =>
    workspaceId == null
      ? (["teams", tournamentId] as const)
      : (["teams", tournamentId, workspaceId] as const),
  teamsCount: (tournamentId: number) => ["teams", tournamentId, "count"] as const,
  heroPlaytime: (tournamentId: number) =>
    ["hero-playtime", "tournament", tournamentId] as const,
  standings: (tournamentId: number, workspaceId?: number | null) =>
    workspaceId == null
      ? (["standings", tournamentId] as const)
      : (["standings", tournamentId, workspaceId] as const),
  bracketStandings: (tournamentId: number, workspaceId?: number | null) =>
    workspaceId == null
      ? (["standings", tournamentId, "bracket"] as const)
      : (["standings", tournamentId, "bracket", workspaceId] as const),
  encounters: (tournamentId: number, workspaceId?: number | null) =>
    workspaceId == null
      ? (["encounters", "tournament", tournamentId] as const)
      : (["encounters", "tournament", tournamentId, workspaceId] as const),
  /** Every FFA lobby of one stage, and one lobby on the encounter page. Both
   *  sit under the `["ffa", tournamentId]` prefix so a result write — which
   *  moves the whole group's table, not one row — stales them together. */
  ffaStage: (tournamentId: number, stageId: number) =>
    ["ffa", tournamentId, "stage", stageId] as const,
  ffaLobby: (tournamentId: number, encounterId: number) =>
    ["ffa", tournamentId, "lobby", encounterId] as const,
  /** That shared prefix, for the writes that move every lobby of a tournament. */
  ffaAll: (tournamentId: number) => ["ffa", tournamentId] as const,
  encountersOverview: (workspaceId?: number | null) =>
    workspaceId == null
      ? (["encounters", "overview"] as const)
      : (["encounters", "overview", workspaceId] as const),
  overallStatistics: (workspaceId?: number | null) =>
    workspaceId == null
      ? (["statistics", "overall"] as const)
      : (["statistics", "overall", workspaceId] as const),
  encountersPage: (
    tournamentId: number,
    workspaceId: number | null | undefined,
    page: number,
    search: string,
  ) => [...tournamentQueryKeys.encounters(tournamentId, workspaceId), page, search] as const,
  registration: (workspaceId: number, tournamentId: number) =>
    ["registration", workspaceId, tournamentId] as const,
  registrationsList: (workspaceId: number, tournamentId: number) =>
    ["registrations-list", workspaceId, tournamentId] as const,
  registrationForm: (workspaceId: number, tournamentId: number) =>
    ["registration-form", workspaceId, tournamentId] as const,
  /** The public roster of registered teams (pre-formation). Distinct from
   *  `teams`, which is the post-balancer materialized `tournament.team` list. */
  registrationTeams: (workspaceId: number, tournamentId: number) =>
    ["registration-teams", workspaceId, tournamentId] as const,
  /** Organizer view: same rows plus invites, and optionally terminal teams. The
   *  flag is part of the key because the two results are different data, not a
   *  filtered view of one cache entry. */
  registrationTeamsAdmin: (
    workspaceId: number,
    tournamentId: number,
    includeTerminal: boolean,
  ) => ["registration-teams-admin", workspaceId, tournamentId, includeTerminal] as const,
  /** The captain's invite picker: registrants on no team. */
  registrationFreeAgents: (workspaceId: number, tournamentId: number) =>
    ["registration-free-agents", workspaceId, tournamentId] as const,
  /** Invites addressed to the CURRENT user. No user id in the key: the server
   *  scopes it from the token, and a per-user key would imply the cache could
   *  legitimately hold another account's offers. Cleared on sign-out with the
   *  rest of the authenticated cache. */
  registrationMyInvites: (workspaceId: number, tournamentId: number) =>
    ["registration-my-invites", workspaceId, tournamentId] as const,
  /** A team's full invite history. Keyed by TEAM, not tournament: it is fetched
   *  only when a captain or organizer expands one team's section, and keying it
   *  by tournament would make every team share — and invalidate — one entry. */
  registrationInviteHistory: (workspaceId: number, teamId: number) =>
    ["registration-invite-history", workspaceId, teamId] as const,
  subscriptionStatus: (tournamentId: number) =>
    ["subscription-status", tournamentId] as const,
  draftBoard: (tournamentId: number) => ["draft", tournamentId, "board"] as const,
  draftSessions: (tournamentId: number) => ["draft", tournamentId, "sessions"] as const,
  draftSession: (sessionId: number) => ["draft", "session", sessionId] as const,
  draftFeasibility: (sessionId: number) =>
    ["draft", "session", sessionId, "feasibility"] as const,
  draftPickOptions: (pickId: number) => ["draft", "pick", pickId, "options"] as const,
  /** Every team's fit shares this prefix, so one invalidation refreshes them all. */
  draftTeamFits: (sessionId: number) => ["draft", "session", sessionId, "fit"] as const,
  draftTeamFit: (sessionId: number, teamId: number) =>
    ["draft", "session", sessionId, "fit", teamId] as const,
  draftTeamQueues: (sessionId: number) => ["draft", "session", sessionId, "queue"] as const,
  draftTeamQueue: (sessionId: number, teamId: number) =>
    ["draft", "session", sessionId, "queue", teamId] as const,
  draftJournal: (sessionId: number) => ["draft", "session", sessionId, "journal"] as const,
  draftPlayerCard: (userId: number) => ["draft", "player-card", userId] as const,
  /** The public tournament list, and the bare prefix every admin write drops. */
  list: () => ["tournaments"] as const,
  listPage: (workspaceId: KeyPart, status: KeyPart, type: KeyPart, query: KeyPart, sort: KeyPart) =>
    ["tournaments", "list", workspaceId, status, type, query, sort] as const,
  facets: (workspaceId: KeyPart, status: KeyPart, type: KeyPart, query: KeyPart) =>
    ["tournaments", "facets", workspaceId, status, type, query] as const,
  /** The workspace's own slice, or the platform-wide one under `"global"`. */
  byWorkspace: (workspaceScope: KeyPart) => ["tournaments", workspaceScope] as const,
  allActive: () => ["tournaments", "all-active"] as const,
  /** The picker feed: every tournament, name-sorted, no paging. */
  selectOptions: () => ["tournaments-select-options"] as const,
  overview: (tournamentId: KeyPart) => ["tournament-overview", tournamentId] as const,
  /** The bare `detail` prefix: every tournament's overview at once. */
  detailRoot: () => ["tournament"] as const,
  teamsAll: () => ["teams"] as const,
  standingsAll: () => ["standings"] as const,
  /** The registration form as the registrant sees it (no organizer fields). */
  registrationFormPublic: (tournamentId: KeyPart) =>
    ["registration-form-public", tournamentId] as const,
  /** Keyed by the invite token, which is all an unauthenticated visitor holds. */
  registrationInvitePreview: (token: KeyPart) =>
    ["registration-team-invite-preview", token] as const,
};
