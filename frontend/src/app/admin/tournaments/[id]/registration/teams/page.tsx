"use client";

import { useParams } from "next/navigation";

import { FlowNodeSelect } from "@/components/kit/FlowNodeSelect";
import { FlowNodeControls } from "@/components/tournaments/FlowNodeControls";
import { FLOW_NODE_PARAM, useFlowNodeParam } from "@/hooks/useFlowNodeParam";
import { usePermissions } from "@/hooks/usePermissions";
import { useQueryParams } from "@/hooks/useQueryParams";
import { nodesOfKind, poolRegistrationNodeId } from "@/lib/tournament/flow-nodes";

import { RegistrationTeamsBrowser } from "../../components/RegistrationTeamsBrowser";
import { tabError, tabFallback, useHubTournamentQuery } from "../../hubQueries";

/**
 * The teams captains registered, organizer side.
 *
 * Its own section rather than a switcher inside `entries`: the layout only
 * offers it when `team_formation` is `registration`, which is also the only
 * case where the read returns anything.
 *
 * The export writes into one registered-mode formation node (`?node=`), and the teams listed are those of the
 * registration node feeding it. A tournament with no such formation lists the first registration node's teams and
 * cannot export.
 */
export default function RegistrationTeamsPage() {
  const params = useParams<{ id: string }>();
  const tournamentId = Number(params.id);
  const validTournamentId =
    Number.isFinite(tournamentId) && tournamentId > 0 ? tournamentId : null;
  const { canAccessPermission } = usePermissions();

  // Already in cache — the shell runs the same query under the same key.
  const tournamentQuery = useHubTournamentQuery(tournamentId);
  const tournament = tournamentQuery.data;
  const formationNodeId = useFlowNodeParam(tournament, "formation", "registered");
  const formationNode = nodesOfKind(tournament, "formation").find((node) => node.id === formationNodeId);
  const registrationNodeId = poolRegistrationNodeId(formationNode) ?? nodesOfKind(tournament, "registration")[0]?.id ?? null;
  const { setParams } = useQueryParams();

  if (tournamentQuery.isLoading) return tabFallback;
  if (validTournamentId == null || tournament?.workspace_id == null) {
    return tabError(() => void tournamentQuery.refetch());
  }

  if (registrationNodeId == null) return tabError(() => void tournamentQuery.refetch());

  return (
    <div className="space-y-4">
      <FlowNodeSelect
        tournament={tournament}
        kind="formation"
        value={formationNodeId}
        onChange={(nodeId) => setParams({ [FLOW_NODE_PARAM]: nodeId })}
      />
      {formationNode ? (
        <FlowNodeControls
          tournament={tournament}
          node={formationNode}
          canUpdate={canAccessPermission("tournament.update", tournament.workspace_id)}
        />
      ) : null}
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
