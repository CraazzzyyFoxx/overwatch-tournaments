import { LookupItem, PaginatedResponse } from "@/types/pagination.types";
import {
  OwalStack,
  OwalStandings,
  Stage,
  Standings,
  Tournament,
  TournamentFacets,
  TournamentStatus
} from "@/types/tournament.types";
import { apiFetch } from "@/lib/api-fetch";
import { normalizePaginatedResponse } from "@/lib/normalize-paginated-response";

type GetStandingsOptions = {
  workspaceId?: number | null;
  includeMatchesHistory?: boolean;
  includeTeamGroup?: boolean;
};

/** The three filter dimensions the list and its facet counts share. */
type TournamentFilterParams = {
  status?: TournamentStatus | null;
  isLeague?: boolean | null;
  query?: string;
};

/**
 * Filters as query params, omitting the ones that are not set. `apiFetch`
 * already drops `null`/`undefined`, but an empty search box would otherwise
 * travel as `query=` and make the backend match on the empty string.
 */
function tournamentFilterQuery(params: TournamentFilterParams): Record<string, unknown> {
  return {
    status: params.status ?? undefined,
    is_league: params.isLeague ?? undefined,
    query: params.query?.trim() ? params.query.trim() : undefined
  };
}

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

  /**
   * The public tournaments list: server-side filtering, sorting and paging.
   *
   * Separate from `getAll` (which pulls every row at `per_page: -1` for
   * selects and dashboards) because this one is the paged, filtered feed the
   * `/tournaments` page scrolls. Empty/absent filters are DROPPED rather than
   * sent as `null`: the backend treats a present-but-null `status` as a real
   * value and would match nothing.
   */
  static async listTournaments(params: {
    workspaceId?: number | null;
    status?: TournamentStatus | null;
    isLeague?: boolean | null;
    query?: string;
    sort?: "start_date" | "participants_count";
    order?: "asc" | "desc";
    page?: number;
    perPage?: number;
  }): Promise<PaginatedResponse<Tournament>> {
    return apiFetch(`/api/v1/tournaments`, {
      query: {
        page: params.page ?? 1,
        per_page: params.perPage ?? 24,
        sort: params.sort ?? "start_date",
        order: params.order ?? "desc",
        workspace_id: params.workspaceId,
        entities: ["stages", "participants_count", "teams_count"],
        ...tournamentFilterQuery(params)
      }
    })
      .then((response) => response.json())
      .then((response: PaginatedResponse<Tournament>) => normalizePaginatedResponse(response));
  }

  /** Counts for the filter chips of the list above, under the same filters. */
  static async getFacets(params: {
    workspaceId?: number | null;
    status?: TournamentStatus | null;
    isLeague?: boolean | null;
    query?: string;
  }): Promise<TournamentFacets> {
    return apiFetch(`/api/v1/tournaments/facets`, {
      query: {
        workspace_id: params.workspaceId,
        ...tournamentFilterQuery(params)
      }
    }).then((response) => response.json());
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

  // `ref` is the raw `/tournaments/{ref}` URL segment: the current slug, a
  // legacy numeric id, or an old slug an admin rename retired -- the backend
  // resolves all three to the same tournament (see resolve_public_ref).
  static async getPublicOverview(ref: string | number): Promise<Tournament> {
    return apiFetch(`/api/v1/tournaments/${ref}`, {
      skipWorkspace: true,
      query: {
        entities: [
          "stages",
          "participants_count",
          "registrations_count",
          "teams_count",
          // Costs one extra query server-side (`flows.py` gates it behind this
          // opt-in), paid once here so the shell's link row needs no read of its
          // own — the same payload already feeds the hero and the section nav.
          "links",
          // The tournament's OWN division grid. Without this entity the read
          // returns `division_grid_version: null` and every consumer silently
          // falls back to the global OW ladder (`getDefaultDivisionGrid`), so
          // the draft room rendered ladder divisions instead of the grid the
          // tournament is actually seeded and balanced on.
          "division_grid_version",
          // Which seats the roster has. The teams list draws role glyphs only
          // for a shape with role slots, and the overview's format card reads
          // the slot line off it; without the entity the read says `null` and
          // both fall back to per-player roles — meaningless in a flex event.
          "roster_shape",
          // The published regulations. Costs no query (it is a column on the
          // row) but is gated all the same: it is a document, and the six
          // schemas that nest TournamentRead must not carry a copy each. Read
          // here because this one payload is the whole page shell — the Rules
          // tab's presence AND its content both come off it.
          "rules",
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
    return apiFetch(`/api/v1/tournaments/${id}/stages`, {
      skipWorkspace: true,
    }).then((response) => response.json());
  }
}
