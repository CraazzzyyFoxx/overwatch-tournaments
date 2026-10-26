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
  /** Under `stages`: the skeleton is a function of the saved stage, so the
   *  stage itself is in the key and any change to it refetches. */
  stageBracketPreview: (tournamentId: number, stageId: number, stage: unknown) =>
    ["tournament", tournamentId, "stages", stageId, "bracket-preview", stage] as const,
  streams: (tournamentId: number) => ["tournament", tournamentId, "streams"] as const,
  /** Participants' past broadcasts. No realtime resource: staleTime alone keeps it fresh. */
  vods: (tournamentId: number) => ["tournament", tournamentId, "vods"] as const,
  links: (tournamentId: number) => ["tournament", tournamentId, "links"] as const,
  /** `tournamentId` is nullable here: the admin browsers key this list by the
   *  scope chip, and "no tournament picked" is its own cache entry. */
  teams: (tournamentId: KeyPart, workspaceId?: number | null) =>
    workspaceId == null
      ? (["teams", tournamentId] as const)
      : (["teams", tournamentId, workspaceId] as const),
  teamsCount: (tournamentId: number) => ["teams", tournamentId, "count"] as const,
  /** The tournament's character playtime (its own game and workspace, so the id names the whole scope). */
  characterPlaytime: (tournamentId: number) =>
    ["character-playtime", "tournament", tournamentId] as const,
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
  /** The organizer's read of the same stage. A separate entry on purpose: it
   *  carries the hidden columns the public read drops, and one shared key would
   *  serve whichever of the two answers landed in the cache first. Still under
   *  the `["ffa", tournamentId]` prefix, so `ffaAll` — and with it every
   *  realtime invalidation (`lib/realtime/resources.ts:67-78`) — stales it
   *  together with the public tables. */
  ffaStageAdmin: (tournamentId: number, stageId: number) =>
    ["ffa", tournamentId, "stage", stageId, "admin"] as const,
  /** That shared prefix, for the writes that move every lobby of a tournament. */
  ffaAll: (tournamentId: number) => ["ffa", tournamentId] as const,
  /** `discipline` null/absent is every game; a concrete code narrows every aggregate and strip. */
  encountersOverview: (workspaceId?: number | "all" | null, discipline?: string | null) =>
    workspaceId == null
      ? (["encounters", "overview", discipline ?? "all"] as const)
      : (["encounters", "overview", workspaceId, discipline ?? "all"] as const),
  overallStatistics: (workspaceId?: number | "all" | null) =>
    workspaceId == null
      ? (["statistics", "overall"] as const)
      : (["statistics", "overall", workspaceId] as const),
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
  /** One session's board, whoever owns the draft: the room's cache, patched by the session's own topic. */
  draftSessionBoard: (sessionId: number) => ["draft", "session", sessionId, "board"] as const,
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
  draftPlayerCard: (userId: number, discipline: string) => ["draft", "player-card", userId, discipline] as const,
  /** One discipline's constructor catalog: the engine's leaf/constraint registry plus that game's item groups and
   *  presets. The discipline is part of the key, so another game's presets never answer for this one. */
  pickBanRulesCatalog: (discipline: KeyPart) => ["pick-ban-rules", "catalog", discipline] as const,
  /** The validator's verdict on one authored ruleset. The ruleset itself is
   *  part of the key: every edit is a different question, and the answer to the
   *  previous one must not stand in for it. */
  pickBanRulesValidation: (
    tournamentId: KeyPart,
    kind: KeyPart,
    mode: KeyPart,
    ruleset: unknown,
  ) => ["pick-ban-rules", "validate", tournamentId, kind, mode, ruleset] as const,
  /** What one ruleset does to a whole series. Keyed by the pool too, since the
   *  worst-case counts are computed against it. */
  pickBanRulesPreview: (
    tournamentId: KeyPart,
    kind: KeyPart,
    mode: KeyPart,
    bestOf: KeyPart,
    ruleset: unknown,
    pool: unknown,
  ) => ["pick-ban-rules", "preview", tournamentId, kind, mode, bestOf, ruleset, pool] as const,
  /** The public tournament list, and the bare prefix every admin write drops. */
  list: () => ["tournaments"] as const,
  /**
   * One workspace's admin list of one game, or of every game under `"all"`; under `list()`, so every admin write drops
   * it.
   */
  adminList: (workspaceId: KeyPart, discipline: KeyPart) => ["tournaments", "admin", workspaceId, discipline] as const,
  /** `discipline` is a concrete code, or `"all"` for the all-games directory view. */
  listPage: (
    workspaceId: KeyPart,
    discipline: KeyPart,
    status: KeyPart,
    type: KeyPart,
    query: KeyPart,
    sort: KeyPart
  ) => ["tournaments", "list", workspaceId, discipline, status, type, query, sort] as const,
  facets: (workspaceId: KeyPart, discipline: KeyPart, status: KeyPart, type: KeyPart, query: KeyPart) =>
    ["tournaments", "facets", workspaceId, discipline, status, type, query] as const,
  /** The workspace's own slice, or the platform-wide one under `"global"`. */
  byWorkspace: (workspaceScope: KeyPart) => ["tournaments", workspaceScope] as const,
  allActive: () => ["tournaments", "all-active"] as const,
  /** The picker feed: every tournament of the workspace (or of all, `"all"`), no paging. */
  selectOptions: (workspaceId: KeyPart) => ["tournaments-select-options", workspaceId] as const,
  overview: (tournamentId: KeyPart) => ["tournament-overview", tournamentId] as const,
  /** The latest series with parsed logs: its last map is a card's picture when there is no cover. */
  latestPlayed: (tournamentId: number) => ["tournament-latest-played", tournamentId] as const,
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
