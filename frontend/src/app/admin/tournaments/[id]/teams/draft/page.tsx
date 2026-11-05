"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { FlowNodeSelect } from "@/components/kit/FlowNodeSelect";
import { PhaseStrip } from "@/components/kit/PhaseStrip";
import { FLOW_NODE_PARAM, useFlowNodeParam } from "@/hooks/useFlowNodeParam";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";

import { useDraftPhases } from "../../components/draft/draft-phases";
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
  const formationNodeId = useFlowNodeParam(tournamentQuery.data, "formation");
  const { setParams } = useQueryParams();

  // Same key and fetcher the dashboard mounts, so this is one request shared
  // with it — the phase belongs to the page, above the two screens the session
  // status chooses between, and reading the status is the whole cost.
  const boardQuery = useQuery({
    queryKey: tournamentQueryKeys.draftBoard(tournamentId, formationNodeId ?? 0),
    queryFn: () => draftService.getTournamentBoard(tournamentId, formationNodeId!),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0 && formationNodeId != null
  });
  const sessionStatus = boardQuery.data?.session?.status ?? null;
  const phases = useDraftPhases(sessionStatus);

  if (tournamentQuery.isLoading) {
    return tabFallback;
  }

  // A live or paused session renders the control room, whose status hero
  // already says where the draft is: the strip would be a second readout.
  const controlRoom = sessionStatus === "live" || sessionStatus === "paused";

  return (
    <div className="space-y-4">
      <FlowNodeSelect
        tournament={tournamentQuery.data}
        kind="formation"
        value={formationNodeId}
        onChange={(nodeId) => setParams({ [FLOW_NODE_PARAM]: nodeId })}
      />
      {controlRoom ? null : <PhaseStrip phases={phases} />}
      {formationNodeId != null && (
        <DraftSessionDashboard
          tournamentId={tournamentId}
          formationNodeId={formationNodeId}
          canManage={canAccessPermission("team.create", workspaceId)}
        />
      )}
    </div>
  );
}
