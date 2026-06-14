import { useQuery } from "@tanstack/react-query";

import rankService from "@/services/rank.service";
import { RankHistoryQuery } from "@/types/rank.types";

const STALE_TIME = 60_000;

export function useUserRankHistory(userId: number, params: RankHistoryQuery = {}) {
  return useQuery({
    queryKey: ["rank-history", "user", userId, params],
    queryFn: () => rankService.getUserRankHistory(userId, params),
    staleTime: STALE_TIME,
    enabled: Number.isFinite(userId)
  });
}

export function useBattleTagRankHistory(battleTagId: number, params: RankHistoryQuery = {}) {
  return useQuery({
    queryKey: ["rank-history", "battle-tag", battleTagId, params],
    queryFn: () => rankService.getBattleTagRankHistory(battleTagId, params),
    staleTime: STALE_TIME,
    enabled: Number.isFinite(battleTagId)
  });
}

export function useUserCurrentRanks(userId: number, platform?: "pc" | "console") {
  return useQuery({
    queryKey: ["rank-history", "current", userId, platform],
    queryFn: () => rankService.getUserCurrentRanks(userId, platform),
    staleTime: STALE_TIME,
    enabled: Number.isFinite(userId)
  });
}
