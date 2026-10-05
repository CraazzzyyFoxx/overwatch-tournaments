import {
  TournamentDivisionStatistics,
  TournamentStatistics,
  TournamentOverall,
  PlayerStatistics
} from "@/types/statistics.types";
import { apiFetch } from "@/lib/api/fetch";
import { PaginatedResponse } from "@/types/pagination.types";

// Platform aggregates (totals, champions, win rates, per-tournament history)
// move when a tournament or a parsed log lands, not per request. Server-side
// reads are held in the Next Data Cache for this long (seconds), so a homepage
// or /statistics render that misses the nginx cache costs a React render, not
// a gateway round-trip per section. Every route here is edge.AuthNone (the
// gateway forwards no identity), so the body is the same for every viewer:
// skipAuth keeps Authorization out of the request and out of the Data Cache
// key, leaving one entry per URL (workspace_id). With the bearer in the key, a
// forged session cookie minted a fresh entry on every render. Client
// (react-query) fetches ignore the `next` option.
const STATS_TTL_SECONDS = 60;

interface StatsOpts {
  workspaceId?: number | "all";
  skipWorkspace?: boolean;
}

function buildWorkspaceOpts(opts?: StatsOpts) {
  return {
    skipWorkspace: opts?.skipWorkspace,
    skipAuth: true,
    query: opts?.workspaceId != null ? { workspace_id: opts.workspaceId } : undefined,
    next: { revalidate: STATS_TTL_SECONDS },
  };
}

export default class statisticsService {
  static async getTournaments(opts?: StatsOpts): Promise<TournamentStatistics[]> {
    return apiFetch("/api/v1/tournaments/statistics/history", buildWorkspaceOpts(opts)).then(
      (res) => res.json()
    );
  }

  static async getTournamentsDivision(opts?: StatsOpts): Promise<TournamentDivisionStatistics[]> {
    return apiFetch("/api/v1/tournaments/statistics/division", buildWorkspaceOpts(opts)).then(
      (res) => res.json()
    );
  }

  static async getOverallStatistics(opts?: StatsOpts): Promise<TournamentOverall> {
    return apiFetch("/api/v1/tournaments/statistics/overall", buildWorkspaceOpts(opts)).then(
      (res) => res.json()
    );
  }

  static async getChampions(opts?: StatsOpts): Promise<PaginatedResponse<PlayerStatistics>> {
    const base = buildWorkspaceOpts(opts);
    return apiFetch("/api/v1/statistics/champion", {
      ...base,
      query: { ...base.query, sort: "value", order: "desc" },
    }).then((res) => res.json());
  }

  static async getTopWinratePlayers(opts?: StatsOpts): Promise<PaginatedResponse<PlayerStatistics>> {
    const base = buildWorkspaceOpts(opts);
    return apiFetch("/api/v1/statistics/winrate", {
      ...base,
      query: { ...base.query, sort: "value", order: "desc" },
    }).then((res) => res.json());
  }

  static async getTopWonMapsPlayers(opts?: StatsOpts): Promise<PaginatedResponse<PlayerStatistics>> {
    const base = buildWorkspaceOpts(opts);
    return apiFetch("/api/v1/statistics/won-maps", {
      ...base,
      query: { ...base.query, sort: "value", order: "desc" },
    }).then((res) => res.json());
  }
}
