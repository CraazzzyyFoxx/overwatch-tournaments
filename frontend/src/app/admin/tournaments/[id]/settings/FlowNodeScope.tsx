"use client";

import { Fragment, type ReactNode } from "react";

import { FlowNodeSelect } from "@/components/kit/FlowNodeSelect";
import { FLOW_NODE_PARAM, useFlowNodeParam } from "@/hooks/useFlowNodeParam";
import { useQueryParams } from "@/hooks/useQueryParams";
import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

/**
 * Scopes a settings screen to one registration or formation node: the picker (only with several nodes), then
 * `children` for the chosen node, remounted when it changes so an unsaved edit never lands on another node. A
 * tournament without a node of the kind renders `fallback` (nothing by default).
 */
export function FlowNodeScope({
  kind,
  tournament,
  fallback = null,
  children
}: Readonly<{
  kind: "registration" | "formation";
  tournament: Tournament;
  fallback?: ReactNode;
  children: (node: TournamentFlowNode) => ReactNode;
}>) {
  const nodeId = useFlowNodeParam(tournament, kind);
  const { setParams } = useQueryParams();
  const node = nodesOfKind(tournament, kind).find((candidate) => candidate.id === nodeId);
  if (!node) return fallback;
  return (
    <>
      <FlowNodeSelect
        tournament={tournament}
        kind={kind}
        value={node.id}
        onChange={(next) => setParams({ [FLOW_NODE_PARAM]: next })}
      />
      <Fragment key={node.id}>{children(node)}</Fragment>
    </>
  );
}
