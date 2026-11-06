"use client";

import { useQueries } from "@tanstack/react-query";

import { useAuthProfile } from "@/hooks/useAuthProfile";
import { currentRegistrationNode, nodesOfKind } from "@/lib/tournament/flow-nodes";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationService from "@/services/registration.service";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

/**
 * The registration node the viewer's own entry, check-in and team panel bind to: `currentRegistrationNode`, but with the
 * signed-in viewer's entries in `check_in` nodes taken into account, so a Day 1 entrant still checks in while Day 2 is
 * `open`. A tournament with one registration node needs no lookup. The probes share the my-registration cache keys.
 */
export function useViewerRegistrationNode(
  tournament: Pick<Tournament, "id" | "workspace_id" | "flow_nodes">
): TournamentFlowNode | null {
  const { user, status } = useAuthProfile();
  const authenticated = status === "authenticated" && user !== null;
  const nodes = nodesOfKind(tournament, "registration");
  const probed = authenticated && nodes.length > 1 ? nodes.filter((node) => node.status === "check_in") : [];
  const entries = useQueries({
    queries: probed.map((node) => ({
      queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id, node.id),
      queryFn: () => registrationService.getMyRegistration(tournament.id, node.id)
    }))
  });
  const entryNodeIds = probed.filter((_node, index) => entries[index]?.data).map((node) => node.id);
  return currentRegistrationNode(tournament, entryNodeIds);
}
