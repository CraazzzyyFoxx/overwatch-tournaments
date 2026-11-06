"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminQueryKeys } from "@/lib/admin/query-keys";
import adminService from "@/services/admin.service";
import teamService from "@/services/team.service";

/**
 * What the stage editor reads: the stages, the tournament, the team catalogue and the stage progress. The Bracket tab
 * and the Flow tab's stage inspector call it with the same keys, so they share one cache entry.
 */
export function useBracketTabData(tournamentId: number) {
  const stagesQuery = useQuery({
    queryKey: adminQueryKeys.stages(tournamentId),
    queryFn: () => adminService.getStages(tournamentId)
  });

  const tournamentQuery = useQuery({
    queryKey: adminQueryKeys.tournament(tournamentId),
    queryFn: () => adminService.getTournament(tournamentId)
  });

  const teamsQuery = useQuery({
    queryKey: adminQueryKeys.tournamentTeamCatalog(tournamentId),
    queryFn: () => teamService.getAll({ tournamentId, sort: "name", order: "asc" })
  });
  const teams = teamsQuery.data?.results ?? [];

  const stages = stagesQuery.data ?? [];

  const progressQuery = useQuery({
    queryKey: adminQueryKeys.stagesProgress(tournamentId),
    queryFn: () => adminService.getStagesProgress(tournamentId),
    enabled: stages.length > 0
  });
  const stageProgress = useMemo(() => progressQuery.data ?? [], [progressQuery.data]);

  const orderedStages = useMemo(
    () => [...stages].sort((left, right) => left.order - right.order),
    [stages]
  );
  const progressByStageId = useMemo(
    () => new Map(stageProgress.map((progress) => [progress.stage_id, progress])),
    [stageProgress]
  );

  // The editor reads all four: a failed team catalogue would draw "0 teams"
  // and empty pickers, which is a lie, not a state.
  const failedQuery = [stagesQuery, tournamentQuery, teamsQuery, progressQuery].find(
    (query) => query.isError
  );

  return {
    stagesQuery,
    tournamentQuery,
    teamsQuery,
    progressQuery,
    orderedStages,
    progressByStageId,
    teams,
    isTeamsLoading: teamsQuery.isLoading,
    failedQuery
  };
}
