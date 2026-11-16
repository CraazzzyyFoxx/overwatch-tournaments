import {
  CharacterWithUserStats,
  EncounterWithUserStats,
  LobbyLeaderboard,
  UserCatalogResponse,
  UserCharacterCompareResponse,
  UserCompareBaselineMode,
  UserCompareResponse,
  User,
  UserBestTeammate,
  UserMatchesSummary,
  UserMapRead,
  UserMapsSummary,
  UserOverviewResponse,
  UserOverviewStats,
  UserDraftCard,
  UserProfile,
  MinimizedUser,
  UserTournamentList,
  UserTournamentWithStats, CareerResponse} from "@/types/user.types";
import { PaginatedResponse, SearchPaginationParams } from "@/types/pagination.types";
import { AchievementRarity } from "@/types/achievement.types";
import { apiFetch } from "@/lib/api/fetch";
import { scopeQuery, type StatsScope } from "@/lib/site/stats-scope";
import type { RoleRef } from "@/lib/roster/role-ref";

// A rated role of the read's game; `null` selects players with no rated assignment; omission means no filter.
function roleQuery(role: RoleRef | null | undefined): string | undefined {
  return role === undefined ? undefined : JSON.stringify(role);
}

// Public, workspace-scoped profile reads are cached in the Next Data Cache for
// this long (seconds) when fetched server-side. Tagged for on-demand
// revalidation: mutations call the `revalidateUser` server action
// (src/app/actions/users.ts) to bust "users" / `user:<id>`. Client (react-query)
// fetches ignore the `next` option.
const USER_TTL_SECONDS = 300;

export default class userService {
  /**
   * `options.workspaceId`, when provided (even as `null`), pins the request to
   * that workspace explicitly instead of resolving it from ambient request
   * headers/cookies. Required for callers running inside `unstable_cache`
   * (e.g. the sitemap), where Next.js forbids calling `headers()`/`cookies()`.
   */
  static async getAll(
    params: SearchPaginationParams,
    options?: { workspaceId?: string | number | null }
  ): Promise<PaginatedResponse<User>> {
    const hasWorkspaceOverride = options !== undefined;
    return apiFetch("/api/v1/users", {
      query: {
        ...params,
        workspace_id: hasWorkspaceOverride ? options?.workspaceId ?? undefined : undefined
      },
      // Explicit workspace override == "no ambient request state" (unstable_cache
      // caller, e.g. sitemap): skip both the workspace-header and access-cookie
      // reads so no dynamic API is called inside the cache boundary.
      skipWorkspace: hasWorkspaceOverride,
      skipAuth: hasWorkspaceOverride
    }).then((res) => res.json());
  }
  static async getUserByName(name: string): Promise<User> {
    const apiName = name.replace("#", "-");
    return apiFetch(`/api/v1/users/${encodeURIComponent(apiName)}`, {
      query: {
        entities: ["social_accounts"]
      },
      next: { revalidate: USER_TTL_SECONDS, tags: ["users"] }
    }).then((res) => res.json());
  }
  /** A player's profile in one game, or across every game (`discipline: null`, spec §6.6). */
  static async getUserProfile(id: number, discipline: string | null, scope?: StatsScope): Promise<UserProfile> {
    return apiFetch(`/api/v1/users/${id}/profile`, {
      query: { ...scopeQuery(scope), discipline: discipline ?? undefined },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  /** The draft room's player card in one game: career totals, per-role and per-character maps,
   *  last five events. `workspaceId` pins the scope — `"all"` for the players
   *  index on the platform apex, where rows span every workspace. */
  static async getDraftCard(
    id: number,
    discipline: string,
    workspaceId?: number | "all" | null
  ): Promise<UserDraftCard> {
    return apiFetch(`/api/v1/users/${id}/draft-card`, {
      query: { discipline, ...(workspaceId != null ? { workspace_id: workspaceId } : {}) },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  static async getUserTournament(
    id: number,
    tournamentId: number | null
  ): Promise<UserTournamentWithStats | null> {
    return apiFetch(`/api/v1/users/${id}/tournaments/${tournamentId}`, {
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    })
      .then((res) => {
        if (res.status === 200) {
          return res.json();
        }
        return null;
      })
      .catch((error) => {
        console.error("Error fetching user tournament data:", error);
        return null;
      });
  }
  /** A player's tournaments: one game's, or every game's when `discipline` is `null` (each row names its own), with
   *  once each the grid versions the rows name. `workspaceId` pins the read: a number/`null` behaves as before,
   *  `"all"` reads every workspace (platform apex only). */
  static async getUserTournaments(
    id: number,
    discipline: string | null,
    workspaceId?: number | "all" | null
  ): Promise<UserTournamentList> {
    const query = { discipline, ...(workspaceId != null ? { workspace_id: workspaceId } : {}) };
    const skipWorkspace = workspaceId === null;
    return apiFetch(`/api/v1/users/${id}/tournaments`, {
      query,
      skipWorkspace,
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  /** Lazy per-tournament dossier detail: one tournament's encounters (with
   *  per-match stats). Split out of `getUserTournaments` so the list fetch
   *  doesn't ship every tournament's encounter/match history up front —
   *  called only for the tournament currently open in the dossier. Cached
   *  by the gateway with full event-driven invalidation (tournament_id is
   *  a path param), same as `getUserTournament`. */
  static async getUserTournamentEncounters(
    id: number,
    tournamentId: number
  ): Promise<EncounterWithUserStats[]> {
    return apiFetch(`/api/v1/users/${id}/tournaments/${tournamentId}/encounters`, {
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  static async getUserMaps(
    id: number,
    discipline: string,
    {
      page = 1,
      perPage = 15,
      sort = "winrate",
      order = "desc",
      query = "",
      minCount,
      modeId,
      tournamentId,
      scope
    }: {
      page?: number;
      perPage?: number;
      sort?: string;
      order?: string;
      query?: string;
      minCount?: number;
      modeId?: number | null;
      tournamentId?: number | null;
      scope?: StatsScope;
    } = {}
  ): Promise<PaginatedResponse<UserMapRead>> {
    return apiFetch(`/api/v1/users/${id}/maps`, {
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"],
        min_count: minCount,
        mode_id: modeId,
        tournament_id: tournamentId,
        entities: ["parent", "character_stats"],
        discipline,
        ...scopeQuery(scope)
      }
    }).then((res) => res.json());
  }

  static async getUserMapsSummary(
    id: number,
    discipline: string,
    {
      query = "",
      minCount,
      modeId,
      tournamentId,
      scope
    }: {
      query?: string;
      minCount?: number;
      modeId?: number | null;
      tournamentId?: number | null;
      scope?: StatsScope;
    } = {}
  ): Promise<UserMapsSummary> {
    return apiFetch(`/api/v1/users/${id}/maps/summary`, {
      query: {
        query,
        fields: ["name"],
        min_count: minCount,
        mode_id: modeId,
        tournament_id: tournamentId,
        entities: ["parent"],
        discipline,
        ...scopeQuery(scope)
      }
    }).then((res) => res.json());
  }
  /** A player's encounters: one game's, or every game's when `discipline` is `null` (each row names its own). */
  static async getUserEncounters(
    id: number,
    discipline: string | null,
    page: number,
    perPage: number = 10,
    sort: string = "played_at",
    order: string = "desc",
    entities: string[],
    filters?: {
      result?: "win" | "loss" | "draw";
      stage?: "group" | "playoffs" | "finals";
      mvp1?: boolean;
      hasLogs?: boolean;
      opponent?: string;
    },
    scope?: StatsScope
  ): Promise<PaginatedResponse<EncounterWithUserStats>> {
    return apiFetch(`/api/v1/users/${id}/encounters`, {
      query: {
        page: page,
        per_page: perPage,
        sort: sort,
        order: order,
        entities,
        result: filters?.result,
        stage: filters?.stage,
        mvp1: filters?.mvp1 ? true : undefined,
        has_logs: filters?.hasLogs ? true : undefined,
        opponent: filters?.opponent || undefined,
        discipline,
        ...scopeQuery(scope)
      },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}:encounters`] }
    }).then((res) => res.json());
  }
  /** Every character the player has eligible play on in one game, with the requested stat codes. */
  static async getUserCharacters(
    id: number,
    discipline: string,
    { stats, tournamentId, scope, signal }: { stats?: string[]; tournamentId?: number; scope?: StatsScope; signal?: AbortSignal } = {}
  ): Promise<PaginatedResponse<CharacterWithUserStats>> {
    return apiFetch(`/api/v1/users/${id}/characters`, {
      signal,
      query: {
        per_page: -1,
        sort: "id",
        order: "asc",
        stats,
        tournament_id: tournamentId,
        discipline,
        ...scopeQuery(scope)
      },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  /** A player's collected game career (`discipline`: the game that collects it; 404 for one that collects none). */
  static async getUserCareer(
    id: number,
    discipline: string,
    { signal }: { signal?: AbortSignal } = {}
  ): Promise<CareerResponse> {
    return apiFetch(`/api/v1/users/${id}/career`, {
      signal,
      query: { discipline },
      skipWorkspace: true,
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  static async getUserAchievements(
    id: number,
    {
      tournamentId,
      withoutTournament,
      includeLocked,
      scope,
      discipline,
      entities = ["tournaments", "matches"]
    }: {
      tournamentId?: number;
      withoutTournament?: boolean;
      includeLocked?: boolean;
      scope?: StatsScope;
      /** One game's rules only (earned and locked); omitted = every game's (the admin person hub). */
      discipline?: string;
      /** The links each achievement carries (where it was earned); `[]` reads none. */
      entities?: ("tournaments" | "matches")[];
    } = {}
  ): Promise<AchievementRarity[]> {
    return apiFetch(`/api/v1/achievements/user/${id}`, {
      query: {
        entities,
        tournament_id: tournamentId,
        without_tournament: withoutTournament,
        include_locked: includeLocked,
        discipline,
        ...scopeQuery(scope)
      },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  static async getUserBestTeammates(
    id: number,
    discipline: string,
    perPage: number = 5,
    scope?: StatsScope
  ): Promise<PaginatedResponse<UserBestTeammate>> {
    return apiFetch(`/api/v1/users/${id}/teammates`, {
      query: {
        per_page: perPage,
        sort: "winrate",
        order: "desc",
        discipline,
        ...scopeQuery(scope)
      },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  static async getUserMatchesSummary(id: number, discipline: string, scope?: StatsScope): Promise<UserMatchesSummary> {
    return apiFetch(`/api/v1/users/${id}/matches/summary`, {
      query: { ...scopeQuery(scope), discipline },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}:encounters`] }
    }).then((res) => res.json());
  }
  /** Full per-stat ranking of every player in a tournament lobby (public). */
  static async getTournamentLeaderboard(
    userId: number,
    tournamentId: number,
    stat: string
  ): Promise<LobbyLeaderboard> {
    return apiFetch(`/api/v1/users/${userId}/tournaments/${tournamentId}/leaderboard`, {
      query: { stat }
    }).then((res) => res.json());
  }
  static async searchUsers(query: string, signal?: AbortSignal): Promise<MinimizedUser[]> {
    return apiFetch(`/api/v1/users/search`, {
      query: { query },
      signal
    }).then((res) => res.json());
  }

  static async getUsersOverview({
    discipline,
    page = 1,
    perPage = 20,
    sort = "name",
    order = "asc",
    query,
    role,
    divisions,
    hasLogs,
    minEncounters,
    workspaceId,
    signal
  }: {
    /** One game, or `null` for every game of the scope (the game-bound `role`/`divisions` must then be omitted). */
    discipline: string | null;
    page?: number;
    perPage?: number;
    sort?:
      | "id"
      | "name"
      | "tournaments_count"
      | "achievements_count"
      | "avg_placement"
      | "winrate"
      | "best_placement";
    order?: "asc" | "desc";
    query?: string;
    role?: RoleRef | null;
    /** Division numbers; a player matches when any (filtered) role sits in the set. */
    divisions?: number[];
    /** Only players with parsed match logs. */
    hasLogs?: boolean;
    /** `sort=winrate` only: below this many encounters a player is ordered last. */
    minEncounters?: number;
    /** A workspace id, or `"all"` for every workspace (platform apex only). */
    workspaceId?: number | "all" | null;
    signal?: AbortSignal;
  }): Promise<UserOverviewResponse> {
    return apiFetch("/api/v1/users/overview", {
      signal,
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"],
        role: roleQuery(role),
        divisions,
        has_logs: hasLogs || undefined,
        min_encounters: minEncounters,
        discipline: discipline ?? undefined,
        workspace_id: workspaceId ?? undefined
      }
    }).then((res) => res.json());
  }

  static async getUsersOverviewStats({
    discipline,
    query,
    role,
    divisions,
    hasLogs,
    workspaceId,
    signal
  }: {
    /** One game, or `null` for every game of the scope (the game-bound `role`/`divisions` must then be omitted). */
    discipline: string | null;
    query?: string;
    role?: RoleRef | null;
    divisions?: number[];
    hasLogs?: boolean;
    workspaceId?: number | "all" | null;
    signal?: AbortSignal;
  }): Promise<UserOverviewStats> {
    return apiFetch("/api/v1/users/overview/stats", {
      signal,
      query: {
        query,
        role: roleQuery(role),
        divisions,
        has_logs: hasLogs || undefined,
        discipline: discipline ?? undefined,
        workspace_id: workspaceId ?? undefined
      }
    }).then((res) => res.json());
  }

  static async getUsersCatalog({
    discipline,
    query,
    role,
    divisions,
    hasLogs,
    letter,
    perLetter = 12,
    maxLetters = 27,
    workspaceId,
    signal
  }: {
    /** One game, or `null` for every game of the scope (the game-bound `role`/`divisions` must then be omitted). */
    discipline: string | null;
    query?: string;
    role?: RoleRef | null;
    divisions?: number[];
    hasLogs?: boolean;
    letter?: string;
    perLetter?: number;
    maxLetters?: number;
    workspaceId?: number | "all" | null;
    signal?: AbortSignal;
  }): Promise<UserCatalogResponse> {
    return apiFetch("/api/v1/users/overview/catalog", {
      signal,
      query: {
        query,
        role: roleQuery(role),
        divisions,
        has_logs: hasLogs || undefined,
        letter,
        per_letter: perLetter,
        max_letters: maxLetters,
        discipline: discipline ?? undefined,
        workspace_id: workspaceId ?? undefined
      }
    }).then((res) => res.json());
  }

  static async getUserCompare(
    userId: number,
    {
      discipline,
      baseline = "global",
      targetUserId,
      role,
      divMin,
      divMax,
      tournamentId,
      workspaceId,
      signal
    }: {
      discipline: string;
      baseline?: UserCompareBaselineMode;
      targetUserId?: number;
      role?: RoleRef;
      divMin?: number;
      divMax?: number;
      tournamentId?: number;
      workspaceId?: number | "all";
      signal?: AbortSignal;
    }
  ): Promise<UserCompareResponse> {
    return apiFetch(`/api/v1/users/${userId}/compare`, {
      signal,
      query: {
        baseline,
        target_user_id: targetUserId,
        role: roleQuery(role),
        div_min: divMin,
        div_max: divMax,
        tournament_id: tournamentId,
        discipline,
        workspace_id: workspaceId
      }
    }).then((res) => res.json());
  }

  static async getUserCharacterCompare(
    userId: number,
    {
      discipline,
      baseline = "global",
      targetUserId,
      leftEntityId,
      rightEntityId,
      mapId,
      role,
      divMin,
      divMax,
      tournamentId,
      workspaceId,
      stats,
      signal
    }: {
      discipline: string;
      baseline?: UserCompareBaselineMode;
      targetUserId?: number;
      leftEntityId?: number;
      rightEntityId?: number;
      mapId?: number;
      role?: RoleRef;
      divMin?: number;
      divMax?: number;
      tournamentId?: number;
      workspaceId?: number | "all";
      stats?: string[];
      signal?: AbortSignal;
    }
  ): Promise<UserCharacterCompareResponse> {
    return apiFetch(`/api/v1/users/${userId}/compare/characters`, {
      signal,
      query: {
        baseline,
        target_user_id: targetUserId,
        left_entity_id: leftEntityId,
        right_entity_id: rightEntityId,
        map_id: mapId,
        role: roleQuery(role),
        div_min: divMin,
        div_max: divMax,
        tournament_id: tournamentId,
        discipline,
        workspace_id: workspaceId,
        stats
      }
    }).then((res) => res.json());
  }
}
