import { Hero, HeroLeaderboardEntry, HeroPlaytime } from "@/types/hero.types";
import { LookupItem, PaginatedResponse } from "@/types/pagination.types";
import { LogStatsName } from "@/types/stats.types";
import { apiFetch } from "@/lib/api-fetch";

export default class heroService {
  static async lookup(): Promise<LookupItem[]> {
    return apiFetch("app", "heroes/lookup").then((res) => res.json());
  }

  static async getAll({
    page = 1,
    perPage = -1,
    sort = "name",
    order = "asc",
    query
  }: {
    page?: number;
    perPage?: number;
    sort?: "id" | "name" | "slug";
    order?: "asc" | "desc";
    query?: string;
  } = {}): Promise<PaginatedResponse<Hero>> {
    return apiFetch("app","heroes", {
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"]
      }
    }).then((res) => res.json());
  }

  static async getHeroPlaytime(
    page: number = 1,
    perPage: number = 10,
    userId: number | string = "all",
    tournamentId: number | null = null,
    opts?: { workspaceId?: number; skipWorkspace?: boolean }
  ): Promise<PaginatedResponse<HeroPlaytime>> {
    return apiFetch("app", "heroes/statistics/playtime", {
      skipWorkspace: opts?.skipWorkspace,
      query: {
        page,
        per_page: perPage,
        user_id: userId,
        tournament_id: tournamentId,
        sort: "playtime",
        order: "desc",
        ...(opts?.workspaceId != null ? { workspace_id: opts.workspaceId } : {}),
      },
    }).then((res) => res.json());
  }

  static async getHeroLeaderboard(
    heroId: number,
    {
      tournamentId,
      stat = LogStatsName.Performance,
      page = 1,
      perPage = 50
    }: {
      tournamentId?: number | null;
      stat?: LogStatsName;
      page?: number;
      perPage?: number;
    } = {}
  ): Promise<PaginatedResponse<HeroLeaderboardEntry>> {
    return apiFetch("app",`heroes/${heroId}/leaderboard`, {
      query: {
        tournament_id: tournamentId ?? undefined,
        stat,
        page,
        per_page: perPage
      }
    }).then((res) => res.json());
  }
}
