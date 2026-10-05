import { PaginatedResponse } from "@/types/pagination.types";
import { apiFetch } from "@/lib/api/fetch";
import { Achievement, AchievementEarned } from "@/types/achievement.types";
import { scopeQuery, type StatsScope } from "@/lib/site/stats-scope";

export default class achievementsService {
  /** `workspaceId` may be `"all"` — every workspace (platform apex only). */
  static async getAll(page: number, perPage: number, workspaceId?: number | "all" | null): Promise<PaginatedResponse<Achievement>> {
    return apiFetch(`/api/v1/achievements`, {
      query: {
        per_page: perPage,
        page: page,
        sort: "rarity",
        order: "asc",
        entities: ["count"],
        ...(workspaceId ? { workspace_id: workspaceId } : {}),
      }
    }).then((res) => res.json());
  }
  static async getOne(id: number, scope?: StatsScope): Promise<Achievement> {
    return apiFetch(`/api/v1/achievements/${id}`, { query: scopeQuery(scope) }).then((res) => res.json());
  }
  static async getUsers(
    id: number,
    page: number,
    perPage: number,
    scope?: StatsScope
  ): Promise<PaginatedResponse<AchievementEarned>> {
    return apiFetch(`/api/v1/achievements/${id}/users`, {
      query: {
        per_page: perPage,
        page: page,
        ...scopeQuery(scope)
      }
    }).then((res) => res.json());
  }
}
