"use client";

import { useMemo } from "react";

import {
  PerformanceV2,
  PlayerAnalytics,
  TeamAnalytics,
  TournamentAnalytics,
} from "@/types/analytics.types";
import {
  buildCommunityVerdict,
  buildKpiRail,
  CommunityVerdict,
  KpiVM,
  resolveImpact,
} from "@/app/(site)/tournaments/analytics/analytics.helpers";

/** A player enriched with a resolved 0–100 impact (v2 score or derived). */
export interface PlayerVM extends PlayerAnalytics {
  impact: number;
}

/** A team with VM players plus the count of flagged players (watch flags). */
export interface TeamVM extends TeamAnalytics {
  players: PlayerVM[];
  flagCount: number;
}

export interface AnalyticsViewModel {
  /** Teams sorted by actual placement (ascending, unranked last). */
  teams: TeamVM[];
  kpis: KpiVM[];
  verdict: CommunityVerdict;
  /** Distinct group count across the bracket (for the hero stat block). */
  groupCount: number;
}

function placementRank(placement: number | null): number {
  return placement == null ? Number.MAX_SAFE_INTEGER : placement;
}

/**
 * Folds the raw `TournamentAnalytics` payload into the fan-facing view model the
 * redesigned page renders: per-player resolved impact, the six KPIs, the
 * who's-the-story verdict and the group count. Memoised on its inputs.
 */
export function useAnalyticsViewModel(
  analytics: TournamentAnalytics | undefined,
  perfByPlayer: Map<number, PerformanceV2> | undefined,
  canReadV2: boolean,
): AnalyticsViewModel | null {
  return useMemo(() => {
    if (!analytics) return null;

    const teams: TeamVM[] = analytics.teams.map((team) => {
      const players = team.players.map<PlayerVM>((player) => ({
        ...player,
        impact: resolveImpact(player, perfByPlayer?.get(player.id), canReadV2),
      }));
      const flagCount = players.reduce(
        (total, player) => total + (player.anomalies.length > 0 ? 1 : 0),
        0,
      );
      return { ...team, players, flagCount };
    });

    teams.sort((a, b) => placementRank(a.placement) - placementRank(b.placement));

    const groups = new Set<string>();
    for (const team of analytics.teams) {
      if (team.group?.name) groups.add(team.group.name);
    }

    return {
      teams,
      kpis: buildKpiRail(analytics.summary, analytics.teams),
      verdict: buildCommunityVerdict(analytics.teams),
      groupCount: groups.size,
    };
  }, [analytics, perfByPlayer, canReadV2]);
}
