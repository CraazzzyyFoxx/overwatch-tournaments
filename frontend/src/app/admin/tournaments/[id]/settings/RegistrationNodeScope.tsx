"use client";

import { Fragment, type ReactNode } from "react";

import { FlowNodeSelect } from "@/components/kit/FlowNodeSelect";
import { FLOW_NODE_PARAM, useFlowNodeParam } from "@/hooks/useFlowNodeParam";
import { useQueryParams } from "@/hooks/useQueryParams";
import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import type { TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

/**
 * Scopes a settings screen to one registration node: the picker (only with several nodes), then `children` for the
 * chosen node, remounted when it changes so an unsaved edit never lands on another node. Renders nothing for a
 * tournament without a registration node.
 */
export function RegistrationNodeScope({
  tournament,
  children
}: Readonly<{ tournament: Tournament; children: (node: TournamentFlowNode) => ReactNode }>) {
  const nodeId = useFlowNodeParam(tournament, "registration");
  const { setParams } = useQueryParams();
  const node = nodesOfKind(tournament, "registration").find((candidate) => candidate.id === nodeId);
  if (!node) return null;
  return (
    <>
      <FlowNodeSelect
        tournament={tournament}
        kind="registration"
        value={node.id}
        onChange={(next) => setParams({ [FLOW_NODE_PARAM]: next })}
      />
      <Fragment key={node.id}>{children(node)}</Fragment>
    </>
  );
}
