"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { adminQueryKeys } from "@/lib/admin/query-keys";
import { encounterQueryKeys } from "@/lib/encounters/query-keys";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import adminService from "@/services/admin.service";
import reportFormService from "@/services/report-form.service";
import tournamentService from "@/services/tournament.service";
import type { EncounterReportsQuery } from "@/types/admin.types";

/**
 * Everything the reports browser needs beside the list itself: the counters,
 * the chip vocabularies, and the organizer's own question definitions.
 */
export function useEncounterReportScope({
  tournamentId,
  workspaceId,
  scopeTournamentId
}: Readonly<{
  tournamentId: number | null;
  workspaceId: number | null;
  scopeTournamentId: number | null;
}>) {
  const scopeParams = useMemo<EncounterReportsQuery | null>(
    () =>
      workspaceId == null
        ? null
        : { workspace_id: workspaceId, tournament_id: scopeTournamentId ?? undefined },
    [workspaceId, scopeTournamentId]
  );

  // Counters take the scope alone — not the chips, not the search box. The
  // numbers answer "how much in this scope needs attention", so they stay put
  // while the admin narrows the list or looks one encounter up, instead of
  // collapsing to what is on screen.
  const statsQuery = useQuery({
    queryKey: encounterQueryKeys.reportStats(scopeParams),
    queryFn: () => adminService.getEncounterReportStats(scopeParams!),
    enabled: scopeParams != null
  });

  const tournamentsQuery = useQuery({
    queryKey: tournamentQueryKeys.list(),
    queryFn: () => tournamentService.getAll(null),
    enabled: workspaceId != null && tournamentId == null
  });

  const stagesQuery = useQuery({
    queryKey: adminQueryKeys.stages(scopeTournamentId),
    queryFn: () => adminService.getStages(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });

  // Organizer-defined questions, so their answers can be labelled instead of
  // shown under raw storage keys. Per tournament, so it is only asked for once
  // a single tournament is in scope; workspace-wide the keys stand in.
  const reportFormQuery = useQuery({
    queryKey: adminQueryKeys.reportForm(scopeTournamentId),
    queryFn: () => reportFormService.getReportForm(scopeTournamentId!),
    enabled: scopeTournamentId != null
  });

  const customFields = useMemo(
    () => reportFormQuery.data?.custom_fields ?? [],
    [reportFormQuery.data]
  );

  return {
    stats: statsQuery.data,
    tournaments: tournamentsQuery.data?.results ?? [],
    stages: stagesQuery.data ?? [],
    customFields
  };
}
