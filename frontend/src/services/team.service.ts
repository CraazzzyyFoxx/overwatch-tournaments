import { PaginatedResponse } from "@/types/pagination.types";
import { Team } from "@/types/team.types";
import { apiFetch } from "@/lib/api-fetch";
import { normalizePaginatedResponse } from "@/lib/normalize-paginated-response";

export type GetTeamsOptions = {
  tournamentId?: number | null;
  workspaceId?: number | null;
  sort?: string;
  order?: "asc" | "desc";
};

export default class teamService {
  static async getAll({
    tournamentId = null,
    workspaceId,
    sort = "avg_sr",
    order = "asc"
  }: GetTeamsOptions = {}): Promise<PaginatedResponse<Team>> {
    return apiFetch(`/api/v1/teams`, {
      ...(workspaceId == null ? {} : { skipWorkspace: true }),
      query: {
        page: 1,
        per_page: -1,
        sort,
        order,
        entities: ["players", "players.user", "placement", "group", "tournament"],
        tournament_id: tournamentId,
        workspace_id: workspaceId
      }
    })
      .then((response) => response.json())
      .then((response: PaginatedResponse<Team>) => normalizePaginatedResponse(response));
  }

  static async getCount(tournament_id: number | null = null): Promise<number> {
    return apiFetch(`/api/v1/teams`, {
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
