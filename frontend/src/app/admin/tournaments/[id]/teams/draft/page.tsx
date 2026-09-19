"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { PhaseStrip } from "@/components/kit/PhaseStrip";
import { usePermissions } from "@/hooks/usePermissions";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";

import { draftPhases } from "../../components/draft/draft-phases";
import { tabFallback, useHubTournamentQuery } from "../../hubQueries";

const DraftSessionDashboard = dynamic(
  () =>
    import("../../components/DraftSessionDashboard").then((module) => ({
      default: module.DraftSessionDashboard
    })),
  { loading: () => tabFallback }
);

export default function TeamsDraftPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const { canAccessPermission } = usePermissions();

  // The layout redirects a balancer tournament away from this segment; only
  // permission wiring here.
  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const workspaceId = tournamentQuery.data?.workspace_id ?? null;

  // Same key and fetcher the dashboard mounts, so this is one request shared
  // with it — the phase belongs to the page, above the two screens the session
  // status chooses between, and reading the status is the whole cost.
  const boardQuery = useQuery({
    queryKey: tournamentQueryKeys.draftBoard(tournamentId),
    queryFn: () => draftService.getTournamentBoard(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0
  });

  if (tournamentQuery.isLoading) {
    return tabFallback;
  }

  return (
    <div className="space-y-4">
      <PhaseStrip phases={draftPhases(boardQuery.data?.session?.status ?? null)} />
      <DraftSessionDashboard
        tournamentId={tournamentId}
        canManage={canAccessPermission("team.create", workspaceId)}
      />
    </div>
  );
}
