import { queryOptions, skipToken } from "@tanstack/react-query";

import { currentRegistrationNode } from "@/lib/tournament/flow-nodes";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationService from "@/services/registration.service";
import registrationTeamService from "@/services/registration-team.service";
import type { Tournament } from "@/types/tournament.types";

/**
 * The roster of the tournament's current registration node (`currentRegistrationNode`) — the participants section's
 * list, and the declared top heroes the teams section's roster expansion reads. Skipped while there is no node.
 *
 * Shared with the Participants route's server prefetch, so both sides build the
 * same key out of one factory.
 */
export function tournamentRegistrationsQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id" | "flow_nodes">
) {
  const nodeId = currentRegistrationNode(tournament)?.id ?? null;
  return queryOptions({
    queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id, nodeId ?? 0),
    queryFn: nodeId == null ? skipToken : () => registrationService.listRegistrations(tournament.id, nodeId)
  });
}

/** The signed-in viewer's own entry at the current registration node; skipped while there is no node. */
export function tournamentMyRegistrationQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id" | "flow_nodes">
) {
  const nodeId = currentRegistrationNode(tournament)?.id ?? null;
  return queryOptions({
    queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id, nodeId ?? 0),
    queryFn: nodeId == null ? skipToken : () => registrationService.getMyRegistration(tournament.id, nodeId)
  });
}

/** The public roster of registered teams at the current registration node; skipped while there is no node. */
export function tournamentRegistrationTeamsQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id" | "flow_nodes">
) {
  const nodeId = currentRegistrationNode(tournament)?.id ?? null;
  return queryOptions({
    queryKey: tournamentQueryKeys.registrationTeams(tournament.workspace_id, tournament.id, nodeId ?? 0),
    queryFn: nodeId == null ? skipToken : () => registrationTeamService.listPublic(tournament.id, nodeId)
  });
}

/**
 * The form definition that names every column of that roster. Without it the
 * participants table has rows but no columns, so it is a first-paint read too.
 */
export function tournamentRegistrationFormQueryOptions(
  tournament: Pick<Tournament, "id" | "workspace_id">
) {
  return queryOptions({
    queryKey: tournamentQueryKeys.registrationForm(tournament.workspace_id, tournament.id),
    queryFn: () => registrationService.getForm(tournament.id)
  });
}
