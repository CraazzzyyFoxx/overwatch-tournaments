import { apiFetch } from "@/lib/api-fetch";
import {
  CurrentRanksResponse,
  RankHistoryQuery,
  RankHistoryResponse
} from "@/types/rank.types";

function historyQuery(params: RankHistoryQuery = {}) {
  return {
    platform: params.platform,
    role: params.role,
    battle_tag_id: params.battleTagId,
    date_from: params.dateFrom,
    date_to: params.dateTo,
    granularity: params.granularity ?? "raw"
  };
}

export default class rankService {
  static async getUserRankHistory(
    userId: number,
    params: RankHistoryQuery = {}
  ): Promise<RankHistoryResponse> {
    return apiFetch("parser", `users/${userId}/rank-history`, {
      query: historyQuery(params),
      skipWorkspace: true
    }).then((res) => res.json());
  }

  static async getBattleTagRankHistory(
    battleTagId: number,
    params: RankHistoryQuery = {}
  ): Promise<RankHistoryResponse> {
    return apiFetch("parser", `battle-tags/${battleTagId}/rank-history`, {
      query: historyQuery(params),
      skipWorkspace: true
    }).then((res) => res.json());
  }

  static async getUserCurrentRanks(
    userId: number,
    platform?: "pc" | "console"
  ): Promise<CurrentRanksResponse> {
    return apiFetch("parser", `users/${userId}/current-ranks`, {
      query: { platform },
      skipWorkspace: true
    }).then((res) => res.json());
  }
}
