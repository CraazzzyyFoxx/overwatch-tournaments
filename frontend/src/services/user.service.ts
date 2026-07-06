import {
  EncounterWithUserStats,
  UserCatalogResponse,
  UserCompareBaselineMode,
  UserCompareResponse,
  UserHeroCompareResponse,
  User,
  UserBestTeammate,
  UserMatchesSummary,
  UserMapRead,
  UserMapsSummary,
  UserOverviewRow,
  UserOverviewStats,
  UserProfile,
  MinimizedUser,
  UserRoleType,
  UserTournament,
  UserTournamentWithStats
} from "@/types/user.types";
import { PaginatedResponse, SearchPaginationParams } from "@/types/pagination.types";
import { HeroWithUserStats } from "@/types/hero.types";
import { AchievementRarity } from "@/types/achievement.types";
import { LogStatsName } from "@/types/stats.types";
import { apiFetch } from "@/lib/api-fetch";

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
      skipWorkspace: hasWorkspaceOverride
    }).then((res) => res.json());
  }
  static async getUserByName(name: string): Promise<User> {
    const apiName = name.replace("#", "-");
    return apiFetch(`/api/v1/users/${encodeURIComponent(apiName)}`, {
      query: {
        entities: ["twitch", "discord", "battle_tag"]
      },
      next: { revalidate: USER_TTL_SECONDS, tags: ["users"] }
    }).then((res) => res.json());
  }
  static async getUserProfile(id: number): Promise<UserProfile> {
    return apiFetch(`/api/v1/users/${id}/profile`, {
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
  static async getUserTournaments(id: number, workspaceId?: number | null): Promise<UserTournament[]> {
    const query = workspaceId !== undefined && workspaceId !== null ? { workspace_id: workspaceId } : undefined;
    const skipWorkspace = workspaceId === null;
    return apiFetch(`/api/v1/users/${id}/tournaments`, {
      query,
      skipWorkspace,
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  static async getUserMaps(
    id: number,
    {
      page = 1,
      perPage = 15,
      sort = "winrate",
      order = "desc",
      query = "",
      minCount,
      gamemodeId,
      tournamentId
    }: {
      page?: number;
      perPage?: number;
      sort?: string;
      order?: string;
      query?: string;
      minCount?: number;
      gamemodeId?: number | null;
      tournamentId?: number | null;
    } = {}
  ): Promise<PaginatedResponse<UserMapRead>> {
    const entities = ["gamemode", "hero_stats"];

    return apiFetch(`/api/v1/users/${id}/maps`, {
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"],
        min_count: minCount,
        gamemode_id: gamemodeId,
        tournament_id: tournamentId,
        entities
      }
    }).then((res) => res.json());
  }

  static async getUserMapsSummary(
    id: number,
    {
      query = "",
      minCount,
      gamemodeId,
      tournamentId
    }: { query?: string; minCount?: number; gamemodeId?: number | null; tournamentId?: number | null } = {}
  ): Promise<UserMapsSummary> {
    return apiFetch(`/api/v1/users/${id}/maps/summary`, {
      query: {
        query,
        fields: ["name"],
        min_count: minCount,
        gamemode_id: gamemodeId,
        tournament_id: tournamentId,
        entities: ["gamemode"]
      }
    }).then((res) => res.json());
  }
  static async getUserEncounters(
    id: number,
    page: number,
    perPage: number = 10,
    sort: string = "id",
    order: string = "desc",
    entities: string[] = [
      "tournament",
      "stage",
      "stage_item",
      "home_team",
      "home_team.players",
      "away_team",
      "away_team.players",
      "matches.map"
    ],
    filters?: {
      result?: "win" | "loss" | "draw";
      stage?: "group" | "playoffs" | "finals";
      mvp1?: boolean;
      hasLogs?: boolean;
      opponent?: string;
    }
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
        opponent: filters?.opponent || undefined
      },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}:encounters`] }
    }).then((res) => res.json());
  }
  static async getUserHeroes(
    id: number,
    stats?: LogStatsName[],
    tournamentId?: number
  ): Promise<PaginatedResponse<HeroWithUserStats>> {
    return apiFetch(`/api/v1/users/${id}/heroes`, {
      query: {
        per_page: -1,
        sort: "id",
        order: "asc",
        stats,
        tournament_id: tournamentId
      }
    }).then((res) => res.json());
  }
  static async getUserAchievements(
    id: number,
    {
      tournamentId,
      withoutTournament,
      includeLocked
    }: {
      tournamentId?: number;
      withoutTournament?: boolean;
      includeLocked?: boolean;
    } = {}
  ): Promise<AchievementRarity[]> {
    return apiFetch(`/api/v1/achievements/user/${id}`, {
      query: {
        entities: ["tournaments", "matches"],
        tournament_id: tournamentId,
        without_tournament: withoutTournament,
        include_locked: includeLocked
      }
    }).then((res) => res.json());
  }
  static async getUserBestTeammates(
    id: number,
    perPage: number = 5
  ): Promise<PaginatedResponse<UserBestTeammate>> {
    return apiFetch(`/api/v1/users/${id}/teammates`, {
      query: {
        per_page: perPage,
        sort: "winrate",
        order: "desc"
      },
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}`] }
    }).then((res) => res.json());
  }
  static async getUserMatchesSummary(id: number): Promise<UserMatchesSummary> {
    return apiFetch(`/api/v1/users/${id}/matches/summary`, {
      next: { revalidate: USER_TTL_SECONDS, tags: [`user:${id}:encounters`] }
    }).then((res) => res.json());
  }
  static async searchUsers(query: string, signal?: AbortSignal): Promise<MinimizedUser[]> {
    return apiFetch(`/api/v1/users/search`, {
      query: {
        query: query,
        fields: ["battle_tag"]
      },
      signal
    }).then((res) => res.json());
  }

  static async getUsersOverview({
    page = 1,
    perPage = 20,
    sort = "name",
    order = "asc",
    query,
    role,
    divMin,
    divMax,
    workspaceId
  }: {
    page?: number;
    perPage?: number;
    sort?: "id" | "name" | "tournaments_count" | "achievements_count" | "avg_placement";
    order?: "asc" | "desc";
    query?: string;
    role?: UserRoleType;
    divMin?: number;
    divMax?: number;
    workspaceId?: number | null;
  } = {}): Promise<PaginatedResponse<UserOverviewRow>> {
    return apiFetch("/api/v1/users/overview", {
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"],
        role,
        div_min: divMin,
        div_max: divMax,
        workspace_id: workspaceId ?? undefined
      }
    }).then((res) => res.json());
  }

  static async getUsersOverviewStats({
    query,
    role,
    divMin,
    divMax,
    workspaceId
  }: {
    query?: string;
    role?: UserRoleType;
    divMin?: number;
    divMax?: number;
    workspaceId?: number | null;
  } = {}): Promise<UserOverviewStats> {
    return apiFetch("/api/v1/users/overview/stats", {
      query: {
        query,
        role,
        div_min: divMin,
        div_max: divMax,
        workspace_id: workspaceId ?? undefined
      }
    }).then((res) => res.json());
  }

  static async getUsersCatalog({
    query,
    role,
    divMin,
    divMax,
    letter,
    perLetter = 12,
    maxLetters = 27,
    workspaceId
  }: {
    query?: string;
    role?: UserRoleType;
    divMin?: number;
    divMax?: number;
    letter?: string;
    perLetter?: number;
    maxLetters?: number;
    workspaceId?: number | null;
  } = {}): Promise<UserCatalogResponse> {
    return apiFetch("/api/v1/users/overview/catalog", {
      query: {
        query,
        role,
        div_min: divMin,
        div_max: divMax,
        letter,
        per_letter: perLetter,
        max_letters: maxLetters,
        workspace_id: workspaceId ?? undefined
      }
    }).then((res) => res.json());
  }

  static async getUserCompare(
    userId: number,
    {
      baseline = "global",
      targetUserId,
      role,
      divMin,
      divMax,
      tournamentId
    }: {
      baseline?: UserCompareBaselineMode;
      targetUserId?: number;
      role?: UserRoleType;
      divMin?: number;
      divMax?: number;
      tournamentId?: number;
    } = {}
  ): Promise<UserCompareResponse> {
    return apiFetch(`/api/v1/users/${userId}/compare`, {
      query: {
        baseline,
        target_user_id: targetUserId,
        role,
        div_min: divMin,
        div_max: divMax,
        tournament_id: tournamentId
      }
    }).then((res) => res.json());
  }

  static async getUserHeroCompare(
    userId: number,
    {
      baseline = "global",
      targetUserId,
      leftHeroId,
      rightHeroId,
      mapId,
      role,
      divMin,
      divMax,
      tournamentId,
      stats
    }: {
      baseline?: UserCompareBaselineMode;
      targetUserId?: number;
      leftHeroId?: number;
      rightHeroId?: number;
      mapId?: number;
      role?: UserRoleType;
      divMin?: number;
      divMax?: number;
      tournamentId?: number;
      stats?: LogStatsName[];
    }
  ): Promise<UserHeroCompareResponse> {
    return apiFetch(`/api/v1/users/${userId}/compare/heroes`, {
      query: {
        baseline,
        target_user_id: targetUserId,
        left_hero_id: leftHeroId,
        right_hero_id: rightHeroId,
        map_id: mapId,
        role,
        div_min: divMin,
        div_max: divMax,
        tournament_id: tournamentId,
        stats
      }
    }).then((res) => res.json());
  }
}
