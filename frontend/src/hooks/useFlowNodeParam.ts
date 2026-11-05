"use client";

import { useSearchParams } from "next/navigation";

import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { Tournament } from "@/types/tournament.types";

/** The URL query parameter that names the registration or formation node a screen works on. */
export const FLOW_NODE_PARAM = "node";

/** Names the registration node whose entries a formation screen (balancer, draft setup) reads as its pool; `?node=` there is the formation. */
export const REGISTRATION_NODE_PARAM = "registration_node";

/**
 * The node a node-scoped admin screen works on: `?node=` when it names a node of this kind, else the tournament's
 * first one. `null` while the tournament is not loaded or has no node of the kind. A screen that works on a
 * registration AND a formation node reads the second one from its own `param`.
 */
export function useFlowNodeParam(
  tournament: Pick<Tournament, "flow_nodes"> | null | undefined,
  kind: "registration" | "formation",
  param: string = FLOW_NODE_PARAM
): number | null {
  const searchParams = useSearchParams();
  const nodes = nodesOfKind(tournament, kind);
  const requested = Number(searchParams?.get(param));
  return nodes.find((node) => node.id === requested)?.id ?? nodes[0]?.id ?? null;
}
