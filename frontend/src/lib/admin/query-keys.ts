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
  dashboardStats: (workspaceId: KeyPart) => ["admin", "dashboard", "stats", workspaceId] as const,
  dashboardTournaments: (workspaceId: KeyPart) =>
    ["admin", "dashboard", "tournaments", workspaceId] as const,
  personAchievements: (personId: KeyPart) =>
    ["admin", "person", personId, "achievements"] as const,
  person: (personId: KeyPart) => ["admin", "person", personId] as const,
  playerSubRolesAll: (workspaceId: KeyPart) =>
    ["admin", "player-sub-roles", workspaceId, "all"] as const,
  playerSubRoles: (workspaceId: KeyPart) => ["admin", "player-sub-roles", workspaceId] as const,
  playerSubRolesRoot: () => ["admin", "player-sub-roles"] as const,
  rankCollection: (workspaceId: KeyPart, userId: KeyPart) =>
    ["admin", "rank", "collection", workspaceId, userId] as const,
  rankCurrent: (userId: KeyPart) => ["admin", "rank", "current", userId] as const,
  rankFetchLog: (workspaceId: KeyPart, status: KeyPart, source: KeyPart) =>
    ["admin", "rank", "fetch-log", workspaceId, status, source] as const,
  rankStats: (workspaceId: KeyPart) => ["admin", "rank", "stats", workspaceId] as const,
  rankStatsAll: () => ["admin", "rank", "stats"] as const,
  rankUserSearch: (query: KeyPart) => ["admin", "rank", "user-search", query] as const,
  rank: () => ["admin", "rank"] as const,
  reportForm: (tournamentId: KeyPart) => ["admin", "report-form", tournamentId] as const,
  settings: () => ["admin", "settings"] as const,
  stageBracketPreview: (stageId: KeyPart, stage: unknown) =>
    ["admin", "stage", stageId, "bracket-preview", stage] as const,
  stagePlannedRounds: (stageId: KeyPart) =>
    ["admin", "stage", stageId, "planned-rounds"] as const,
  stages: (tournamentId: KeyPart) => ["admin", "stages", tournamentId] as const,
  stagesProgress: (tournamentId: KeyPart) =>
    ["admin", "stages", tournamentId, "progress"] as const,
  streamsHealth: () => ["admin", "streams", "health"] as const,
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
  tournamentEncountersCount: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "encounters", "count"] as const,
  tournamentEncounters: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "encounters"] as const,
  tournamentLinks: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "links"] as const,
  tournamentStandings: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "standings"] as const,
  tournamentTeamsCount: (tournamentId: KeyPart) =>
    ["admin", "tournament", tournamentId, "teams", "count"] as const,
  tournamentWizardDivisionGrids: (workspaceId: KeyPart) =>
    ["admin", "tournaments", "create", "division-grids", workspaceId] as const,
  tournamentWizardResume: (workspaceId: KeyPart) =>
    ["admin", "tournaments", "wizard-resume", workspaceId] as const,
  tournamentWizardResumeAll: () => ["admin", "tournaments", "wizard-resume"] as const,
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
  playerSubRolesPublic: (workspaceId: KeyPart) => ["player-sub-roles", workspaceId] as const,
  /** The parser's unresolved log names, and the badge counting them. */
  catalogAliasMisses: () => ["admin", "catalog-alias-misses"] as const,
  /** One catalogue entity's list: `heroes`, `maps` or `gamemodes`. */
  contentEntity: (entity: KeyPart) => ["admin", entity] as const,
  /** The alias-resolution picker for one catalogue entity. */
  contentAliasTargets: (entity: KeyPart) => ["admin", entity, "alias-targets"] as const,
  /** The parser console, mounted workspace-wide rather than per tournament. */
  workspaceLogHistory: (workspaceId: KeyPart) =>
    ["admin", "workspace", workspaceId, "log-history"] as const,
};
