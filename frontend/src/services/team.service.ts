import { PaginatedResponse } from "@/types/pagination.types";
import { Team } from "@/types/team.types";
import { apiFetch } from "@/lib/api-fetch";
import { normalizePaginatedResponse } from "@/lib/normalize-paginated-response";

export default class teamService {
  static async getAll(
    tournament_id: number | null = null,
    sort: string = "avg_sr",
    order: string = "asc"
  ): Promise<PaginatedResponse<Team>> {
    return apiFetch("tournament", `teams`, {
      query: {
        page: 1,
        per_page: -1,
        sort: sort,
        order: order,
        entities: ["players", "players.user", "placement", "group", "tournament"],
        tournament_id: tournament_id
      }
    })
      .then((response) => response.json())
      .then((response: PaginatedResponse<Team>) => normalizePaginatedResponse(response));
  }

  static async getCount(tournament_id: number | null = null): Promise<number> {
    return apiFetch("tournament", `teams`, {
      query: {
        page: 1,
        per_page: 1,
        only_count: true,
        tournament_id: tournament_id
      }
    })
      .then((response) => response.json())
      .then((response: PaginatedResponse<Team>) => response.total);
  }
}
