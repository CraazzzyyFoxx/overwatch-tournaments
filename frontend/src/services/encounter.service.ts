import {
  Encounter,
  EncounterFilters,
  EncounterOverview,
  EncounterSavedView,
  MatchWithStats
} from "@/types/encounter.types";
import { PaginatedResponse } from "@/types/pagination.types";
import { apiFetch } from "@/lib/api-fetch";

export default class encounterService {
  static async getEncounter(id: number): Promise<Encounter> {
    return apiFetch(`/api/v1/encounters/${id}`, {
      query: {
        entities: [
          "matches",
          "matches.map",
          "teams",
          "teams.players",
          "teams.placement",
          "teams.players.user",
          "tournament",
          "tournament.division_grid_version",
          "stage",
          "stage_item"
        ]
      }
    }).then((res) => res.json());
  }
  static async getMatch(match_id: number): Promise<MatchWithStats> {
    return apiFetch(`/api/v1/matches/${match_id}`, {
      query: {
        entities: [
          "teams",
          "teams.players",
          "teams.players.user",
          "map",
          "map.gamemode",
          "encounter",
          "encounter.tournament",
          "encounter.stage",
          "encounter.stage_item"
        ]
      }
    }).then((res) => res.json());
  }
  static async getAll(
    page: number,
    query: string,
    tournamentId: number | null = null,
    perPage: number = 15,
    sort: string | null = null,
    order: "asc" | "desc" = "desc",
    workspaceId?: number | null,
    filters: EncounterFilters & { entities?: string[] } = {}
  ): Promise<PaginatedResponse<Encounter>> {
    const { entities, ...restFilters } = filters;
    return apiFetch(`/api/v1/encounters`, {
      query: {
        workspace_id: workspaceId,
        per_page: perPage,
        page: page,
        query: query,
        sort: sort ?? "id",
        order: order,
        entities: entities ?? ["tournament", "stage", "stage_item", "home_team", "away_team"],
        fields: ["name"],
        tournament_id: tournamentId,
        ...restFilters
      }
    }).then((res) => res.json());
  }

  static async getOverview(
    query: string,
    filters: EncounterFilters = {},
    workspaceId?: number | null
  ): Promise<EncounterOverview> {
    return apiFetch(`/api/v1/encounters/overview`, {
      query: {
        workspace_id: workspaceId,
        per_page: -1,
        page: 1,
        query,
        fields: ["name"],
        sort: filters.sort ?? "id",
        order: "desc",
        ...filters
      }
    }).then((res) => res.json());
  }

  static async getSavedViews(workspaceId?: number | null): Promise<EncounterSavedView[]> {
    return apiFetch(`/api/v1/encounters/views`, {
      query: {
        workspace_id: workspaceId
      }
    }).then((res) => res.json());
  }

  static async saveView(
    name: string,
    filters: EncounterFilters & { query?: string },
    workspaceId?: number | null
  ): Promise<EncounterSavedView> {
    return apiFetch(`/api/v1/encounters/views`, {
      method: "POST",
      query: {
        workspace_id: workspaceId
      },
      body: {
        name,
        filters
      }
    }).then((res) => res.json());
  }

  static async deleteView(id: number, workspaceId?: number | null): Promise<void> {
    await apiFetch(`/api/v1/encounters/views/${id}`, {
      method: "DELETE",
      query: {
        workspace_id: workspaceId
      }
    });
  }

  static async getCount(
    tournamentId: number | null = null,
    workspaceId?: number | null
  ): Promise<number> {
    return apiFetch(`/api/v1/encounters`, {
      query: {
        workspace_id: workspaceId,
        per_page: 1,
        page: 1,
        only_count: true,
        tournament_id: tournamentId
      }
    })
      .then((res) => res.json())
      .then((response: PaginatedResponse<Encounter>) => response.total);
  }

  static async getAllMatches(
    page: number,
    perPage: number,
    query: string,
    tournamentId: number | null = null
  ): Promise<PaginatedResponse<MatchWithStats>> {
    return apiFetch(`/api/v1/matches`, {
      query: {
        per_page: perPage,
        page: page,
        query: query,
        sort: "id",
        order: "desc",
        entities: [
          "teams",
          "map",
          "map.gamemode",
          "encounter",
          "encounter.tournament",
          "encounter.stage",
          "encounter.stage_item"
        ],
        tournament_id: tournamentId
      }
    }).then((res) => res.json());
  }
}
