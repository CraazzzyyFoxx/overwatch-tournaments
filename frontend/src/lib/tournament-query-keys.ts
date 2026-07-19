export const tournamentQueryKeys = {
  detail: (tournamentId: number) => ["tournament", tournamentId] as const,
  stages: (tournamentId: number) => ["tournament", tournamentId, "stages"] as const,
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
  draftBoard: (tournamentId: number) => ["draft", tournamentId, "board"] as const,
  draftSession: (sessionId: number) => ["draft", "session", sessionId] as const,
  draftSuggestions: (sessionId: number) =>
    ["draft", "session", sessionId, "suggestions"] as const,
  draftFeasibility: (sessionId: number) =>
    ["draft", "session", sessionId, "feasibility"] as const,
  draftPickOptions: (pickId: number) => ["draft", "pick", pickId, "options"] as const,
};
