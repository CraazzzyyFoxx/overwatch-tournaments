import { PaginatedResponse } from "@/types/pagination.types";
import { apiFetch } from "@/lib/api-fetch";
import { Achievement, AchievementEarned } from "@/types/achievement.types";

export default class achievementsService {
  static async getAll(page: number, perPage: number, workspaceId?: number | null): Promise<PaginatedResponse<Achievement>> {
    return apiFetch("app",`achievements`, {
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
  static async getOne(id: number): Promise<Achievement> {
    return apiFetch("app",`achievements/${id}`).then((res) => res.json());
  }
  static async getUsers(
    id: number,
    page: number,
    perPage: number
  ): Promise<PaginatedResponse<AchievementEarned>> {
    return apiFetch("app",`achievements/${id}/users`, {
      query: {
        per_page: perPage,
        page: page
      }
    }).then((res) => res.json());
  }
}
