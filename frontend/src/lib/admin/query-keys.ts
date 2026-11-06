import type { KeyPart } from "@/lib/query-keys";

/**
 * Keys for the admin workspace: the tournament hub, the collectors (rank,
 * subscriptions, streams), the content catalogue editors, people, teams and the
 * workspace records themselves.
 *
 * `lib/tournament/workspace-query-keys.ts` composes the tournament-scoped
 * entries below into the bundle its invalidation helper walks -- it does not
 * respell them. Achievement rules live in `lib/achievements/query-keys.ts`
 * despite sharing the `admin` root, because the public catalogue reads the same
 * data and has to be invalidated alongside them.
 */
export const adminQueryKeys = {
  auditCount: (workspaceId: KeyPart, entityType: KeyPart, entityId: KeyPart) =>
    ["admin", "audit", "count", workspaceId, entityType, entityId] as const,
  auditHistoryStart: (scope: KeyPart) => ["admin", "audit", "history-start", scope] as const,
  challongeSyncLog: (tournamentId: KeyPart) =>
    ["admin", "challonge-sync-log", tournamentId] as const,
  challongeTeamSyncPreview: (tournamentId: KeyPart) =>
    ["admin", "challonge-team-sync-preview", tournamentId] as const,
  /** Prefix of the organizer dashboard and its activity feed: one realtime flush refetches both. */
  dashboardRoot: () => ["admin", "dashboard"] as const,
  dashboard: (workspaceId: KeyPart) => ["admin", "dashboard", "overview", workspaceId] as const,
  dashboardActivity: (workspaceId: KeyPart, excludeActorId: KeyPart) =>
    ["admin", "dashboard", "activity", workspaceId, excludeActorId] as const,
  /** Outside `dashboardRoot` on purpose: trends move when a tournament finishes, not on realtime flushes. */
  dashboardTrends: (workspaceId: KeyPart) => ["admin", "dashboard-trends", workspaceId] as const,
  /** Finished tournaments since the active ML artifacts were trained (platform health). */
  mlTrainingLag: () => ["admin", "ml-training-lag"] as const,
  personAchievements: (personId: KeyPart) =>
    ["admin", "person", personId, "achievements"] as const,
  person: (personId: KeyPart) => ["admin", "person", personId] as const,
  playerSubRolesAll: (workspaceId: KeyPart, discipline: KeyPart) =>
    ["admin", "player-sub-roles", workspaceId, discipline, "all"] as const,
  playerSubRoles: (workspaceId: KeyPart, discipline?: KeyPart) => discipline === undefined
    ? ["admin", "player-sub-roles", workspaceId] as const
    : ["admin", "player-sub-roles", workspaceId, discipline] as const,
  playerSubRolesRoot: () => ["admin", "player-sub-roles"] as const,
  rankCollection: (workspaceId: KeyPart, discipline: KeyPart, userId: KeyPart) =>
    ["admin", "rank", "collection", workspaceId, discipline, userId] as const,
  rankFetchLog: (workspaceId: KeyPart, discipline: KeyPart, status: KeyPart, source: KeyPart) =>
    ["admin", "rank", "fetch-log", workspaceId, discipline, status, source] as const,
  /** The flat rank-overview table; `params` is the whole filter/sort/page set. */
  rankOverview: (workspaceId: KeyPart, params: unknown) =>
    ["admin", "rank", "overview", workspaceId, params] as const,
  rankStats: (workspaceId: KeyPart, discipline: KeyPart) =>
    ["admin", "rank", "stats", workspaceId, discipline] as const,
  rankStatsAll: () => ["admin", "rank", "stats"] as const,
  rankUserSearch: (query: KeyPart) => ["admin", "rank", "user-search", query] as const,
  rank: () => ["admin", "rank"] as const,
  reportForm: (tournamentId: KeyPart) => ["admin", "report-form", tournamentId] as const,
  settings: () => ["admin", "settings"] as const,
  // The preview keys on the whole draft `stage`, so only the one-argument
  // prefix form matches every cached variant of it (the layout editor
  // invalidates them all after a save).
  stageBracketPreview: (stageId: KeyPart, stage?: unknown) =>
    stage === undefined
      ? (["admin", "stage", stageId, "bracket-preview"] as const)
      : (["admin", "stage", stageId, "bracket-preview", stage] as const),
  stageBracketTemplate: (stageId: KeyPart) =>
    ["admin", "stage", stageId, "bracket-template"] as const,
  // The editor keys on the whole draft `stage` the way `stageBracketPreview`
  // does, so a save that changes seeds or format refetches the rounds; the
  // plain one-argument form reads an already-saved stage.
  stagePlannedRounds: (stageId: KeyPart, stage?: unknown) =>
    stage === undefined
      ? (["admin", "stage", stageId, "planned-rounds"] as const)
      : (["admin", "stage", stageId, "planned-rounds", stage] as const),
  stages: (tournamentId: KeyPart) => ["admin", "stages", tournamentId] as const,
  stagesProgress: (tournamentId: KeyPart) =>
    ["admin", "stages", tournamentId, "progress"] as const,
  streamsHealth: () => ["admin", "streams", "health"] as const,
  streamsTicks: () => ["admin", "streams", "health", "ticks"] as const,
  streams: () => ["admin", "streams"] as const,
  subscriptionsCheckLog: (workspaceId: KeyPart, state: KeyPart, source: KeyPart, provider: KeyPart) =>
    ["admin", "subscriptions", "check-log", workspaceId, state, source, provider] as const,
  subscriptionsCollection: (workspaceId: KeyPart, userId: KeyPart) =>
    ["admin", "subscriptions", "collection", workspaceId, userId] as const,
  subscriptionsStats: (workspaceId: KeyPart) =>
    ["admin", "subscriptions", "stats", workspaceId] as const,
  subscriptionsStatsAll: () => ["admin", "subscriptions", "stats"] as const,
  subscriptionsUserHistory: (workspaceId: KeyPart, userId: KeyPart) =>
    ["admin", "subscriptions", "user-history", workspaceId, userId] as const,
  subscriptionsUserSearch: (query: KeyPart) =>
    ["admin", "subscriptions", "user-search", query] as const,
  subscriptions: () => ["admin", "subscriptions"] as const,
  team: (teamId: KeyPart) => ["admin", "team", teamId] as const,
  tournamentTeamCatalog: (tournamentId: KeyPart) =>
    ["admin", "tournament", "teams", tournamentId] as const,
  tournamentTeams: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "teams"] as const,
  tournament: (tournamentId: KeyPart) => ["admin", "tournament", tournamentId] as const,
  tournamentVoice: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "voice"] as const,
  tournamentFlow: (tournamentId: KeyPart) => ["admin", "tournament", tournamentId, "flow"] as const,
  tournamentTeamFormat: (tournamentId: KeyPart, workspaceId: KeyPart, discipline: KeyPart) =>
    ["admin", "tournament", tournamentId, "team-format", workspaceId, discipline] as const,
  tournamentEncountersCount: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "encounters", "count"] as const,
  tournamentEncounters: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "encounters"] as const,
  tournamentLinks: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "links"] as const,
  /** The Matches → Pre-game rooms overview; the sub-tab badge shares this key. */
  pregameRooms: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "pregame-rooms"] as const,
  /** The personal tables of the tournament's `individual_swiss` stages. */
  tournamentPlayerStandings: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "player-standings"] as const,
  tournamentStandings: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "standings"] as const,
  tournamentTeamsCount: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "teams", "count"] as const,
  users: () => ["admin", "users"] as const,
  matchDetail: (matchId: KeyPart, workspaceId: KeyPart) =>
    ["admin-matches", "detail", matchId, workspaceId] as const,
  matchEncounter: (encounterId: KeyPart, workspaceId: KeyPart) =>
    ["admin-matches", "encounter", encounterId, workspaceId] as const,
  matches: () => ["admin-matches"] as const,
  workspaceDomainVerify: (workspaceId: KeyPart, domain: KeyPart) =>
    ["admin-workspace-domain-verify", workspaceId, domain] as const,
  workspace: (workspaceId: KeyPart) => ["admin-workspace", workspaceId] as const,
  workspaces: () => ["admin-workspaces"] as const,
  workspaceOwner: (workspaceId: KeyPart) => ["workspace-owner", workspaceId] as const,
  playerSubRolesPublic: (workspaceId: KeyPart, discipline: KeyPart) => ["player-sub-roles", workspaceId, discipline] as const,
  /** The parser's unresolved log names, and the badge counting them. */
  catalogAliasMisses: () => ["admin", "catalog-alias-misses"] as const,
  /** The parser console, mounted workspace-wide rather than per tournament. */
  workspaceLogHistory: (workspaceId: KeyPart) =>
    ["admin", "workspace", workspaceId, "log-history"] as const,
  /** A tournament's encounters, as the log bind dialog's picker lists them. */
  logLinkEncounters: (workspaceId: KeyPart, tournamentId: KeyPart) =>
    ["admin", "log-link", "encounters", workspaceId, tournamentId] as const,
};
