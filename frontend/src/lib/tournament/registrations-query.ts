import { queryOptions, skipToken } from "@tanstack/react-query";

import { currentRegistrationNode, listedRegistrationNode } from "@/lib/tournament/flow-nodes";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import registrationService from "@/services/registration.service";
import registrationTeamService from "@/services/registration-team.service";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

type RegistrationTournament = Pick<Tournament, "id" | "workspace_id" | "flow_nodes">;

/**
 * Every read below is of one registration node: `node`, or the tournament's `currentRegistrationNode` when a caller
 * does not know the viewer (the server prefetch). A signed-in surface passes `useViewerRegistrationNode`'s node so a
 * viewer's own entry and team stay in view while another intake is open. Skipped while there is no node.
 */

/**
 * The roster of the registration node — the participants section's list, and the declared top heroes the teams
 * section's roster expansion reads. Before any intake opens it is the first registration node's roster
 * (`listedRegistrationNode`), so the list does not wait forever on a node that is still `draft`.
 *
 * Shared with the Participants route's server prefetch, so both sides build the
 * same key out of one factory.
 */
export function tournamentRegistrationsQueryOptions(
  tournament: RegistrationTournament,
  node: TournamentFlowNode | null = currentRegistrationNode(tournament)
) {
  const nodeId = listedRegistrationNode(tournament, node)?.id ?? null;
  return queryOptions({
    queryKey: tournamentQueryKeys.registrationsList(tournament.workspace_id, tournament.id, nodeId ?? 0),
    queryFn: nodeId == null ? skipToken : () => registrationService.listRegistrations(tournament.id, nodeId)
  });
}

/** The signed-in viewer's own entry at the registration node. */
export function tournamentMyRegistrationQueryOptions(
  tournament: RegistrationTournament,
  node: TournamentFlowNode | null = currentRegistrationNode(tournament)
) {
  const nodeId = node?.id ?? null;
  return queryOptions({
    queryKey: tournamentQueryKeys.registration(tournament.workspace_id, tournament.id, nodeId ?? 0),
    queryFn: nodeId == null ? skipToken : () => registrationService.getMyRegistration(tournament.id, nodeId)
  });
}

/** The public roster of registered teams at the registration node. */
export function tournamentRegistrationTeamsQueryOptions(
  tournament: RegistrationTournament,
  node: TournamentFlowNode | null = currentRegistrationNode(tournament)
) {
  const nodeId = node?.id ?? null;
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
