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
  teams: (tournamentId: number, workspaceId?: number | null) =>
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
  draftSuggestions: (sessionId: number) =>
    ["draft", "session", sessionId, "suggestions"] as const,
  draftFeasibility: (sessionId: number) =>
    ["draft", "session", sessionId, "feasibility"] as const,
  draftPickOptions: (pickId: number) => ["draft", "pick", pickId, "options"] as const,
};
