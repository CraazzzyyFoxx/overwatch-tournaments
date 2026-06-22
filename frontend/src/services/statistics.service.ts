import {
  TournamentDivisionStatistics,
  TournamentStatistics,
  TournamentOverall,
  PlayerStatistics
} from "@/types/statistics.types";
import { apiFetch } from "@/lib/api-fetch";
import { PaginatedResponse } from "@/types/pagination.types";

interface StatsOpts {
  workspaceId?: number;
  skipWorkspace?: boolean;
}

function buildWorkspaceOpts(opts?: StatsOpts) {
  return {
    skipWorkspace: opts?.skipWorkspace,
    query: opts?.workspaceId != null ? { workspace_id: opts.workspaceId } : undefined,
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
