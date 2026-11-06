"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";

import { FlowNodeSelect } from "@/components/kit/FlowNodeSelect";
import { FLOW_NODE_PARAM, useFlowNodeParam } from "@/hooks/useFlowNodeParam";
import { useQueryParams } from "@/hooks/useQueryParams";

import { tabFallback, useHubTournamentQuery } from "../../hubQueries";

// D25: the Google Sheets feed builder lives in a neutral place and is rendered
// by both this hub sub-route (tournament from the path) and the legacy balancer
// route (tournament from the query) until T14 retires the latter.
const SheetsFeedPage = dynamic(() => import("@/components/balancer/feed/SheetsFeedPage"), {
  loading: () => tabFallback
});

export default function RegistrationFeedSubRoutePage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  // The feed writes its rows into one registration node.
  const tournament = useHubTournamentQuery(tournamentId).data;
  const registrationNodeId = useFlowNodeParam(tournament, "registration");
  const { setParams } = useQueryParams();

  return (
    <div className="space-y-4">
      <FlowNodeSelect
        tournament={tournament}
        kind="registration"
        value={registrationNodeId}
        onChange={(nodeId) => setParams({ [FLOW_NODE_PARAM]: nodeId })}
      />
      <SheetsFeedPage
        tournamentId={Number.isFinite(tournamentId) && tournamentId > 0 ? tournamentId : null}
        registrationNodeId={registrationNodeId}
      />
    </div>
  );
}
