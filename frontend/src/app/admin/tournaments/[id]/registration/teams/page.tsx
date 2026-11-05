"use client";

import { useParams } from "next/navigation";

import { useFlowNodeParam } from "@/hooks/useFlowNodeParam";

import { RegistrationTeamsBrowser } from "../../components/RegistrationTeamsBrowser";
import { tabError, tabFallback, useHubTournamentQuery } from "../../hubQueries";

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
  // The export writes the teams of one formation node.
  const formationNodeId = useFlowNodeParam(tournament, "formation");

  if (tournamentQuery.isLoading) return tabFallback;
  if (validTournamentId == null || tournament?.workspace_id == null) {
    return tabError(() => void tournamentQuery.refetch());
  }

  return (
    <RegistrationTeamsBrowser
      tournamentId={validTournamentId}
      workspaceId={tournament.workspace_id}
      discipline={tournament.discipline}
      formationNodeId={formationNodeId}
    />
  );
}
