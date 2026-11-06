import { isSignUpOpen, nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

/** One card per registration node open for sign-up, only for a tournament with several (a single intake keeps the header button). */
export function registrationCardNodes(
  tournament: Pick<Tournament, "flow_nodes">,
  now: Date = new Date()
): TournamentFlowNode[] {
  const nodes = nodesOfKind(tournament, "registration");
  return nodes.length < 2 ? [] : nodes.filter((node) => isSignUpOpen(node, now.getTime()));
}
