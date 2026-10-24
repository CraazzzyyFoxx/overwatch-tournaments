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
  standingsRank,
} from "@/disciplines/overwatch/analytics/analytics.helpers";

/** A player enriched with the 0–100 v2 impact; `null` when the viewer may not read a v2 row for them. */
export interface PlayerVM extends PlayerAnalytics {
  impact: number | null;
}

/** A team with VM players plus the count of flagged players (watch flags). */
export interface TeamVM extends TeamAnalytics {
  players: PlayerVM[];
  flagCount: number;
}

export interface AnalyticsViewModel {
  /** Teams sorted by actual placement, or by forecast until the bracket is played. */
  teams: TeamVM[];
  kpis: KpiVM[];
  verdict: CommunityVerdict;
  /** Distinct group count across the bracket: a group chip is shown only when the rows span more than one. */
  groupCount: number;
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
        impact: resolveImpact(perfByPlayer?.get(player.id), canReadV2),
      }));
      const flagCount = players.reduce(
        (total, player) => total + (player.anomalies.length > 0 ? 1 : 0),
        0,
      );
      return { ...team, players, flagCount };
    });

    teams.sort((a, b) => standingsRank(a) - standingsRank(b));

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
