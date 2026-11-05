"use client";

import { useSearchParams } from "next/navigation";

import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { Tournament } from "@/types/tournament.types";

/** The URL query parameter that names the registration or formation node a screen works on. */
export const FLOW_NODE_PARAM = "node";

/**
 * The node a node-scoped admin screen works on: `?node=` when it names a node of this kind, else the tournament's
 * first one. `null` while the tournament is not loaded or has no node of the kind.
 */
export function useFlowNodeParam(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined,
  kind: "registration" | "formation"
): number | null {
  const searchParams = useSearchParams();
  const nodes = nodesOfKind(tournament, kind);
  const requested = Number(searchParams?.get(FLOW_NODE_PARAM));
  return nodes.find((node) => node.id === requested)?.id ?? nodes[0]?.id ?? null;
}
