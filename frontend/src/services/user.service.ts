import {
  EncounterWithUserStats,
  UserCatalogResponse,
  UserCompareBaselineMode,
  UserCompareResponse,
  UserHeroCompareResponse,
  User,
  UserBestTeammate,
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

export default class userService {
  static async getAll(params: SearchPaginationParams): Promise<PaginatedResponse<User>> {
    return apiFetch("app","users", {
      query: {
        ...params
      }
    }).then((res) => res.json());
  }
  static async getUserByName(name: string): Promise<User> {
    const apiName = name.replace("#", "-");
    return apiFetch("app", `users/${encodeURIComponent(apiName)}`, {
      query: {
        entities: ["twitch", "discord", "battle_tag"]
      }
    }).then((res) => res.json());
  }
  static async getUserProfile(id: number): Promise<UserProfile> {
    return apiFetch("app",`users/${id}/profile`).then((res) => res.json());
  }
  static async getUserTournament(
    id: number,
    tournamentId: number | null
  ): Promise<UserTournamentWithStats | null> {
    return apiFetch("app",`users/${id}/tournaments/${tournamentId}`)
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
    return apiFetch("app", `users/${id}/tournaments`, {
      query,
      skipWorkspace,
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

    return apiFetch("app",`users/${id}/maps`, {
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
    return apiFetch("app",`users/${id}/maps/summary`, {
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
    ]
  ): Promise<PaginatedResponse<EncounterWithUserStats>> {
    return apiFetch("app",`users/${id}/encounters`, {
      query: {
        page: page,
        per_page: perPage,
        sort: sort,
        order: order,
        entities
      }
    }).then((res) => res.json());
  }
  static async getUserHeroes(
    id: number,
    stats?: LogStatsName[],
    tournamentId?: number
  ): Promise<PaginatedResponse<HeroWithUserStats>> {
    return apiFetch("app",`users/${id}/heroes`, {
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
    return apiFetch("app",`achievements/user/${id}`, {
      query: {
        entities: ["tournaments", "matches"],
        tournament_id: tournamentId,
        without_tournament: withoutTournament,
        include_locked: includeLocked
      }
    }).then((res) => res.json());
  }
  /** Direct (browser-navigable) URL for downloading a match's parsed log file. */
  static matchLogDownloadUrl(matchId: number): string {
    return `/api/v1/core/matches/${matchId}/log`;
  }
  static async getUserBestTeammates(id: number): Promise<PaginatedResponse<UserBestTeammate>> {
    return apiFetch("app",`users/${id}/teammates`, {
      query: {
        per_page: 5,
        sort: "winrate",
        order: "desc"
      }
    }).then((res) => res.json());
  }
  static async searchUsers(query: string, signal?: AbortSignal): Promise<MinimizedUser[]> {
    return apiFetch("app",`users/search`, {
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
    divMax
  }: {
    page?: number;
    perPage?: number;
    sort?: "id" | "name" | "tournaments_count" | "achievements_count" | "avg_placement";
    order?: "asc" | "desc";
    query?: string;
    role?: UserRoleType;
    divMin?: number;
    divMax?: number;
  } = {}): Promise<PaginatedResponse<UserOverviewRow>> {
    return apiFetch("app","users/overview", {
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"],
        role,
        div_min: divMin,
        div_max: divMax
      }
    }).then((res) => res.json());
  }

  static async getUsersOverviewStats({
    query,
    role,
    divMin,
    divMax
  }: {
    query?: string;
    role?: UserRoleType;
    divMin?: number;
    divMax?: number;
  } = {}): Promise<UserOverviewStats> {
    return apiFetch("app", "users/overview/stats", {
      query: {
        query,
        role,
        div_min: divMin,
        div_max: divMax
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
    maxLetters = 27
  }: {
    query?: string;
    role?: UserRoleType;
    divMin?: number;
    divMax?: number;
    letter?: string;
    perLetter?: number;
    maxLetters?: number;
  } = {}): Promise<UserCatalogResponse> {
    return apiFetch("app", "users/overview/catalog", {
      query: {
        query,
        role,
        div_min: divMin,
        div_max: divMax,
        letter,
        per_letter: perLetter,
        max_letters: maxLetters
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
    return apiFetch("app",`users/${userId}/compare`, {
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
    return apiFetch("app",`users/${userId}/compare/heroes`, {
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
