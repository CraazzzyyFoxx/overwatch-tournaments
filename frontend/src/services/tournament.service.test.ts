import { beforeEach, describe, expect, it, mock } from "bun:test";

// Capture the real service boundary so tests can assert the public API contract
// without coupling to apiFetch's internal URL serialization.
type Call = {
  path: string;
  options:
    | {
        skipWorkspace?: boolean;
        query?: Record<string, unknown>;
      }
    | undefined;
};
const calls: Call[] = [];

mock.module("@/lib/api-fetch", () => ({
  apiFetch: (
    path: string,
    options?: { skipWorkspace?: boolean; query?: Record<string, unknown> },
  ) => {
    calls.push({ path, options });
    return Promise.resolve({ json: async () => ({ results: [], total: 0 }) });
  },
}));

mock.module("@/lib/normalize-paginated-response", () => ({
  normalizePaginatedResponse: (r: unknown) => r,
}));

const { default: tournamentService } = await import("@/services/tournament.service");

describe("tournamentService.getActive", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("defaults to skipWorkspace: true (platform-wide) when called with no args", async () => {
    await tournamentService.getActive();
    expect(calls[0].options?.skipWorkspace).toBe(true);
  });

  it("forwards skipWorkspace: false when the caller opts into workspace scope", async () => {
    await tournamentService.getActive({ skipWorkspace: false });
    expect(calls[0].options?.skipWorkspace).toBe(false);
  });
});

describe("tournamentService.getPublicOverview", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  // The list is pinned deliberately: every entity costs the read another query
  // server-side (`flows.py` gates each one), so growing it must be a decision
  // somebody made on purpose rather than a line that drifted in. `links` earns
  // its place by replacing a SECOND round trip — the shell renders the link row
  // from this same payload instead of fetching it separately.
  it("loads the fixed public overview without ambient workspace scoping", async () => {
    await tournamentService.getPublicOverview(72);

    expect(calls).toEqual([
      {
        path: "/api/v1/tournaments/72",
        options: {
          skipWorkspace: true,
          query: {
            entities: [
              "stages",
              "participants_count",
              "registrations_count",
              "teams_count",
              "links",
              "division_grid_version",
              // Deliberate, not drift: the teams list draws role glyphs only for
              // a shape with role slots and the overview's format card reads the
              // slot line off it, so without the entity both fall back to
              // per-player roles — meaningless in a flex event.
              "roster_shape",
              // Deliberate too, on a different ground: `rules` costs no query
              // (a column on the row) but is gated on payload size, and this
              // read is where the document is wanted — the shell decides the
              // Rules tab's existence from it and the tab renders it.
              "rules",
            ],
          },
        },
      },
    ]);
  });
});

describe("tournamentService.getStages", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("loads public tournament stages without ambient workspace scoping", async () => {
    await tournamentService.getStages(72);

    expect(calls).toEqual([
      {
        path: "/api/v1/tournaments/72/stages",
        options: {
          skipWorkspace: true,
        },
      },
    ]);
  });
});

// The two reads behind the public `/tournaments` page. Everything the page shows
// is now decided server-side, so these query objects ARE the contract with
// `rpc.tournament.list_tournaments` / `rpc.tournament.tournaments_facets`. The
// page's own tests mock this service, which is exactly why the params it sends
// need pinning here.
describe("tournamentService.listTournaments", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  it("sends paging, sort and the three filters the backend understands", async () => {
    await tournamentService.listTournaments({
      workspaceId: 7,
      status: "live",
      isLeague: false,
      query: "spring",
      sort: "participants_count",
      order: "desc",
      page: 3,
      perPage: 12,
    });

    expect(calls).toEqual([
      {
        path: "/api/v1/tournaments",
        options: {
          query: {
            page: 3,
            per_page: 12,
            sort: "participants_count",
            order: "desc",
            workspace_id: 7,
            entities: ["stages", "participants_count", "teams_count"],
            status: "live",
            is_league: false,
            query: "spring",
          },
        },
      },
    ]);
  });

  // `is_league: false` is a real filter and must survive; the absent ones must
  // not travel at all. A present-but-null `status` would be a value the backend
  // matches against, and an empty `query` would ILIKE '%%' on every row while
  // making the request key differ from the unsearched one.
  it("omits unset filters instead of sending nulls, and keeps is_league false", async () => {
    await tournamentService.listTournaments({
      workspaceId: null,
      status: null,
      isLeague: false,
      query: "   ",
    });

    const query = calls[0].options?.query as Record<string, unknown>;
    expect(query.status).toBeUndefined();
    expect(query.query).toBeUndefined();
    expect(query.is_league).toBe(false);
    expect(query.page).toBe(1);
    expect(query.sort).toBe("start_date");
    expect(query.order).toBe("desc");
  });
});

describe("tournamentService.getFacets", () => {
  beforeEach(() => {
    calls.length = 0;
  });

  // Same filter object as the list, minus paging: the counters describe the
  // filtered set, so any divergence here would show chips that disagree with
  // the rows beneath them.
  it("sends exactly the list's filters and no paging", async () => {
    await tournamentService.getFacets({
      workspaceId: 7,
      status: "registration",
      isLeague: true,
      query: " cup ",
    });

    expect(calls).toEqual([
      {
        path: "/api/v1/tournaments/facets",
        options: {
          query: {
            workspace_id: 7,
            status: "registration",
            is_league: true,
            query: "cup",
          },
        },
      },
    ]);
  });
});
