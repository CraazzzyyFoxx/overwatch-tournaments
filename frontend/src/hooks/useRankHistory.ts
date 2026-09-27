import { useQuery } from "@tanstack/react-query";

import { useLocalStorageState } from "@/hooks/useLocalStorageState";
import rankService from "@/services/rank.service";
import { RankHistoryQuery } from "@/types/rank.types";
import { userQueryKeys } from "@/lib/users/query-keys";

const STALE_TIME = 60_000;

/** The granularities the rank-history UI offers. */
export type Granularity = "date" | "hour" | "raw";

/** UI granularity → the value the rank-history endpoint expects. */
export const BACKEND_GRANULARITY: Record<
  Granularity,
  NonNullable<RankHistoryQuery["granularity"]>
> = {
  date: "daily",
  hour: "hourly",
  raw: "raw"
};

/**
 * How far back to fetch for a granularity. Two weeks reads well as a daily
 * trend, but the same window at hourly/raw grain is an unreadable wall of
 * points, so the finer grains get three days.
 */
export function getDefaultDateFrom(g: Granularity): string {
  const d = new Date();
  d.setDate(d.getDate() - (g === "date" ? 14 : 3));
  return d.toISOString();
}

/**
 * Sole owner of the persisted granularity choice. The two rank-history cards
 * and the chart each used to read and write this key independently, so the
 * selector could disagree with the series that was actually fetched.
 */
export function useRankHistoryGranularity() {
  return useLocalStorageState<Granularity>("rank-history-granularity", "date");
}

export function useUserRankHistory(userId: number, params: RankHistoryQuery = {}) {
  return useQuery({
    queryKey: userQueryKeys.rankHistory(userId, params),
    queryFn: () => rankService.getUserRankHistory(userId, params),
    staleTime: STALE_TIME,
    enabled: Number.isFinite(userId)
  });
}
