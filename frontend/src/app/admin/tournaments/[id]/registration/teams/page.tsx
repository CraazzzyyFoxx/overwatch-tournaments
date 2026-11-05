"use client";

import { useParams } from "next/navigation";

import { FlowNodeSelect } from "@/components/kit/FlowNodeSelect";
import { FLOW_NODE_PARAM, useFlowNodeParam } from "@/hooks/useFlowNodeParam";
import { useQueryParams } from "@/hooks/useQueryParams";

import { RegistrationTeamsBrowser } from "../../components/RegistrationTeamsBrowser";
import { tabError, tabFallback, useHubTournamentQuery } from "../../hubQueries";

/** Names the formation node the export writes into; `?node=` is the registration node the teams belong to. */
const FORMATION_EXPORT_PARAM = "export_node";

/**
 * The teams captains registered, organizer side.
 *
 * Its own section rather than a switcher inside `entries`: the layout only
 * offers it when `team_formation` is `registration`, which is also the only
 * case where the read returns anything.
 */
export default function RegistrationTeamsPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const validTournamentId =
    Number.isFinite(tournamentId) && tournamentId > 0 ? tournamentId : null;

  // Already in cache — the shell runs the same query under the same key.
  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;
  // The teams belong to one registration node; the export writes them into one formation node, chosen apart.
  const registrationNodeId = useFlowNodeParam(tournament, "registration");
  const formationNodeId = useFlowNodeParam(tournament, "formation", FORMATION_EXPORT_PARAM);
  const { setParams } = useQueryParams();

  if (tournamentQuery.isLoading) return tabFallback;
  if (validTournamentId == null || tournament?.workspace_id == null) {
    return tabError(() => void tournamentQuery.refetch());
  }

  if (registrationNodeId == null) return tabError(() => void tournamentQuery.refetch());

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-4">
        <FlowNodeSelect
          tournament={tournament}
          kind="registration"
          value={registrationNodeId}
          onChange={(nodeId) => setParams({ [FLOW_NODE_PARAM]: nodeId })}
        />
        <FlowNodeSelect
          tournament={tournament}
          kind="formation"
          value={formationNodeId}
          onChange={(nodeId) => setParams({ [FORMATION_EXPORT_PARAM]: nodeId })}
        />
      </div>
      <RegistrationTeamsBrowser
        tournamentId={validTournamentId}
        workspaceId={tournament.workspace_id}
        discipline={tournament.discipline}
        registrationNodeId={registrationNodeId}
        formationNodeId={formationNodeId}
      />
    </div>
  );
}
