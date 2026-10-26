import {
  Encounter,
  EncounterFilters,
  EncounterInsights,
  EncounterOverview,
  EncounterSavedFilters,
  EncounterSavedView,
  MatchWithStats
} from "@/types/encounter.types";
import { MatchEvents } from "@/types/killfeed.types";
import { PaginatedResponse } from "@/types/pagination.types";
import type { Tournament } from "@/types/tournament.types";
import { apiFetch } from "@/lib/api/fetch";

export default class encounterService {
  static async getEncounter(id: number): Promise<Encounter> {
    return apiFetch(`/api/v1/encounters/${id}`, {
      skipWorkspace: true,
      query: {
        entities: [
          "matches",
          "matches.map",
          // The detail page names each map's mode; without this the nested
          // `map.parent` comes back null.
          "matches.map.parent",
          "teams",
          "teams.players",
          "teams.placement",
          "teams.players.user",
          // `captain_id` is a user id, so the roster needs the captain resolved
          // to mark the row; `group` names the side's group on the scoreboard.
          "teams.captain",
          "teams.group",
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
      skipWorkspace: true,
      query: {
        entities: [
          "map",
          "map.parent",
          // The seats' source teams carry the logos the header draws; their rosters resolve a registration
          // (a pick/ban target) to the global player an observed member is.
          "encounter",
          "encounter.teams",
          "encounter.teams.players",
          "encounter.tournament",
          "encounter.stage",
          "encounter.stage_item"
        ]
      }
    }).then((res) => res.json());
  }
  static async getMatchKillFeed(match_id: number): Promise<MatchEvents> {
    return apiFetch(`/api/v1/matches/${match_id}/kill-feed`, { skipWorkspace: true }).then((res) => res.json());
  }
  static async getAll(
    page: number,
    query: string,
    tournamentId: number | null = null,
    perPage: number = 15,
    sort: string | null = null,
    order: "asc" | "desc" = "desc",
    workspaceId?: number | "all" | null,
    filters: EncounterFilters & { entities?: string[] } = {},
    opts: { signal?: AbortSignal } = {}
  ): Promise<PaginatedResponse<Encounter>> {
    const { entities, ...restFilters } = filters;
    return apiFetch(`/api/v1/encounters`, {
      signal: opts.signal,
      query: {
        workspace_id: workspaceId,
        per_page: perPage,
        page: page,
        query: query,
        sort: sort ?? "id",
        order: order,
        entities: entities ?? ["tournament", "stage", "stage_item", "teams"],
        fields: ["name"],
        tournament_id: tournamentId,
        ...restFilters
      }
    }).then((res) => res.json());
  }

  /**
   * A tournament's latest series with parsed logs, by play date, with its
   * maps: the map last played in it is the tournament's picture when it has no
   * cover (`lib/tournament/art.ts`). `null` before anything is played.
   */
  static async getLatestPlayed(
    tournament: Pick<Tournament, "id" | "workspace_id">,
    opts: { signal?: AbortSignal; next?: { revalidate: number } } = {}
  ): Promise<Encounter | null> {
    const page: PaginatedResponse<Encounter> = await apiFetch(`/api/v1/encounters`, {
      signal: opts.signal,
      next: opts.next,
      query: {
        workspace_id: tournament.workspace_id,
        tournament_id: tournament.id,
        has_logs: true,
        sort: "played_at",
        order: "desc",
        page: 1,
        per_page: 1,
        entities: ["matches", "matches.map"]
      }
    }).then((res) => res.json());
    return page.results[0] ?? null;
  }

  /** The aggregate reads (overview, insights) take the list's filter params; paging and order mean nothing there. */
  private static aggregateQuery(query: string, filters: EncounterFilters, workspaceId?: number | "all" | null) {
    return {
      workspace_id: workspaceId,
      per_page: -1,
      page: 1,
      query,
      fields: ["name"],
      sort: filters.sort ?? "id",
      order: "desc",
      ...filters
    };
  }

  static async getOverview(
    query: string,
    filters: EncounterFilters = {},
    workspaceId?: number | "all" | null,
    opts: { signal?: AbortSignal } = {}
  ): Promise<EncounterOverview> {
    return apiFetch(`/api/v1/encounters/overview`, {
      signal: opts.signal,
      query: encounterService.aggregateQuery(query, filters, workspaceId)
    }).then((res) => res.json());
  }

  /** Completed encounters only (the server forces the status), so the heavy read is made only while it is shown. */
  static async getInsights(
    query: string,
    filters: EncounterFilters = {},
    workspaceId?: number | "all" | null,
    opts: { signal?: AbortSignal } = {}
  ): Promise<EncounterInsights> {
    return apiFetch(`/api/v1/encounters/insights`, {
      signal: opts.signal,
      query: encounterService.aggregateQuery(query, filters, workspaceId)
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
    filters: EncounterSavedFilters,
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
}
