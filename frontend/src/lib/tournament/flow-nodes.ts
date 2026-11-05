import type { Tournament } from "@/types/tournament.types";
import type { TournamentFlowNode } from "@/types/flow.types";

/** The tournament's nodes of one lifecycle kind, in id order; empty when the read did not ask for `flow_nodes`. */
export function nodesOfKind(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined,
  kind: `${TournamentFlowNode["kind"]}`
): TournamentFlowNode[] {
  return (tournament?.flow_nodes ?? []).filter((node) => `${node.kind}` === kind).sort((a, b) => a.id - b.id);
}

/** The formation node that forms teams by draft: the one a tournament's public draft room follows. */
export function draftFormationNode(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined
): TournamentFlowNode | null {
  return nodesOfKind(tournament, "formation").find((node) => node.config.mode === "draft") ?? null;
}
