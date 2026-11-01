"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import encounterService from "@/services/encounter.service";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { readTimeline } from "./timeline";

/**
 * A match's event timeline, read once per match for every tab that draws it (the breakdown's flow and the
 * timeline share the `matchEvents` key, so opening one warms the other). `enabled: false` keeps a tab that is
 * not on screen from reading it.
 */
export function useMatchTimeline(matchId: number, enabled = true) {
  const query = useQuery({
    queryKey: encounterQueryKeys.matchEvents(matchId),
    queryFn: () => encounterService.getMatchKillFeed(matchId),
    staleTime: 5 * 60_000,
    enabled
  });
  const data = query.data;
  const timeline = useMemo(() => (data ? readTimeline(data.events, data.entities) : null), [data]);
  return { status: query.status, refetch: query.refetch, timeline };
}
