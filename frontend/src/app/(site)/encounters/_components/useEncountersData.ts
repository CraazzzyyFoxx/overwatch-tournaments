"use client";

import { useMemo } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import encounterService from "@/services/encounter.service";
import tournamentService from "@/services/tournament.service";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { LookupItem, PaginatedResponse } from "@/types/pagination.types";
import type { StatsScope } from "@/lib/site/stats-scope";
import type { Encounter, EncounterOverview } from "@/types/encounter.types";

import { ENCOUNTERS_PAGE_SIZE, filtersToApiFilters, type EncounterFilterState } from "./encounters.helpers";

export interface EncountersDataInput {
  initialData: PaginatedResponse<Encounter>;
  initialOverview: EncounterOverview;
  initialFilters: EncounterFilterState;
  initialPage: number;
  effectiveFilters: EncounterFilterState;
  page: number;
  scope: StatsScope;
}

export interface EncountersData {
  listQuery: UseQueryResult<PaginatedResponse<Encounter>>;
  overviewQuery: UseQueryResult<EncounterOverview>;
  tournamentsLookupQuery: UseQueryResult<LookupItem[]>;
}

/**
 * The three reads the encounters index renders from. The list and the overview
 * both seed off the server-rendered payload, but only while the filters still
 * match the ones that payload was built for — otherwise the first client-side
 * filter change would paint the unfiltered page as if it were the answer.
 */
export function useEncountersData({
  initialData,
  initialOverview,
  initialFilters,
  initialPage,
  effectiveFilters,
  page,
  scope
}: EncountersDataInput): EncountersData {
  const currentWorkspaceId = useWorkspaceStore((state) => state.currentWorkspaceId);
  // One value carries the workspace dimension of every read and its cache key.
  const workspaceId = scope === "all" ? "all" : currentWorkspaceId;
  const apiFilters = useMemo(() => filtersToApiFilters(effectiveFilters), [effectiveFilters]);
  const matchesInitial = JSON.stringify(effectiveFilters) === JSON.stringify(initialFilters);

  const listQuery = useQuery({
    queryKey: encounterQueryKeys.list(workspaceId, page, apiFilters, effectiveFilters.query),
    queryFn: () =>
      encounterService.getAll(
        page,
        effectiveFilters.query,
        null,
        ENCOUNTERS_PAGE_SIZE,
        apiFilters.sort ?? "id",
        "desc",
        workspaceId,
        {
          ...apiFilters,
          entities: [
            "tournament",
            "stage",
            "stage_item",
            "home_team",
            "away_team",
            "matches",
            "matches.map"
          ]
        }
      ),
    initialData: page === initialPage && matchesInitial ? initialData : undefined,
    placeholderData: (previous) => previous
  });

  const overviewQuery = useQuery({
    queryKey: encounterQueryKeys.overview(workspaceId, apiFilters, effectiveFilters.query),
    queryFn: () => encounterService.getOverview(effectiveFilters.query, apiFilters, workspaceId),
    initialData: matchesInitial ? initialOverview : undefined,
    placeholderData: (previous) => previous,
    retry: 1
  });

  const tournamentsLookupQuery = useQuery({
    queryKey: encounterQueryKeys.tournamentsLookup(workspaceId),
    queryFn: () => tournamentService.lookup(workspaceId),
    staleTime: 5 * 60_000,
    retry: 1
  });

  return { listQuery, overviewQuery, tournamentsLookupQuery };
}
