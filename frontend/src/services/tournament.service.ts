import { LookupItem, PaginatedResponse } from "@/types/pagination.types";
import { OwalStack, OwalStandings, Stage, Standings, Tournament } from "@/types/tournament.types";
import { apiFetch } from "@/lib/api-fetch";
import { PlayerAnalytics, TournamentAnalytics } from "@/types/analytics.types";
import { normalizePaginatedResponse } from "@/lib/normalize-paginated-response";

type GetStandingsOptions = {
  workspaceId?: number | null;
  includeMatchesHistory?: boolean;
  includeTeamGroup?: boolean;
};

export default class tournamentService {
  static async lookup(
    workspaceId?: number | null,
    isLeague?: boolean | null
  ): Promise<LookupItem[]> {
    return apiFetch("/api/v1/tournaments/lookup", {
      query: {
        workspace_id: workspaceId,
        is_league: isLeague
      }
    }).then((res) => res.json());
  }

  static async getAll(
    isLeague: boolean | null = null,
    workspaceId?: number | null
  ): Promise<PaginatedResponse<Tournament>> {
    return apiFetch(`/api/v1/tournaments`, {
      query: {
        is_league: isLeague,
        workspace_id: workspaceId,
        page: 1,
        per_page: -1,
        sort: "id",
        order: "desc",
        entities: ["stages", "participants_count"]
      }
    })
      .then((response) => response.json())
      .then((response: PaginatedResponse<Tournament>) => normalizePaginatedResponse(response));
  }
  static async getOwalSeasons(workspaceId?: number | null): Promise<string[]> {
    return apiFetch(`/api/v1/tournaments/league/seasons`, {
      query: { workspace_id: workspaceId }
    }).then((response) => response.json());
  }

  static async getOwalStandings(
    season?: string,
    workspaceId?: number | null
  ): Promise<OwalStandings> {
    return apiFetch(`/api/v1/tournaments/league/results`, {
      query: {
        season,
        workspace_id: workspaceId
      }
    }).then((response) => response.json());
  }

  static async getOwalStacks(season?: string, workspaceId?: number | null): Promise<OwalStack[]> {
    return apiFetch(`/api/v1/tournaments/league/stacks`, {
      query: {
        season,
        workspace_id: workspaceId
      }
    }).then((response) => response.json());
  }
  static async getActive(opts?: { skipWorkspace?: boolean }): Promise<PaginatedResponse<Tournament>> {
    return apiFetch(`/api/v1/tournaments`, {
      skipWorkspace: opts?.skipWorkspace ?? true,
      query: {
        page: 1,
        per_page: -1,
        sort: "id",
        order: "desc",
        entities: ["registrations_count"]
      }
    })
      .then((response) => response.json())
      .then((response: PaginatedResponse<Tournament>) => normalizePaginatedResponse(response));
  }

  static async get(id: number): Promise<Tournament> {
    return apiFetch(`/api/v1/tournaments/${id}`, {
      query: {
        entities: ["participants_count", "registrations_count"]
      }
    }).then((response) => response.json());
  }

  static async getPublicOverview(id: number): Promise<Tournament> {
    return apiFetch(`/api/v1/tournaments/${id}`, {
      skipWorkspace: true,
      query: {
        entities: [
          "stages",
          "participants_count",
          "registrations_count",
          "teams_count",
        ],
      },
    }).then((response) => response.json());
  }

  static async getStandings(
    id: number,
    workspaceIdOrOptions?: number | null | GetStandingsOptions
  ): Promise<Standings[]> {
    const options =
      typeof workspaceIdOrOptions === "object" && workspaceIdOrOptions !== null
        ? workspaceIdOrOptions
        : { workspaceId: workspaceIdOrOptions };
    const includeMatchesHistory = options.includeMatchesHistory ?? true;
    const includeTeamGroup = options.includeTeamGroup ?? true;
    const entities = ["stage", "stage_item", "team"];

    if (includeMatchesHistory) {
      entities.push("matches_history");
    }

    if (includeTeamGroup) {
      entities.push("team.group");
    }

    return apiFetch(`/api/v1/tournaments/${id}/standings`, {
      query: {
        workspace_id: options.workspaceId,
        entities
      }
    }).then((response) => response.json());
  }

  static async getStages(id: number): Promise<Stage[]> {
    return apiFetch(`/api/v1/tournaments/${id}/stages`).then((response) => response.json());
  }
}
