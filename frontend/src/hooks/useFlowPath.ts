"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { adminQueryKeys } from "@/lib/admin/query-keys";
import { stepsTo, type FlowStep, type PathNode } from "@/lib/tournament/flow-path";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import adminService from "@/services/admin.service";
import flowService from "@/services/flow.service";
import type { FlowNodeStatus } from "@/types/flow.types";

/**
 * The tournament's flow graph (the cache the bracket's stage feed shares) and what the admin screens say about moving
 * it: a step's name, the steps an action needs first, and running them in order.
 */
export function useFlowPath(tournamentId: number | null) {
  const t = useTranslations("common.flowPath");
  const queryClient = useQueryClient();
  const graphQuery = useQuery({
    queryKey: adminQueryKeys.tournamentFlow(tournamentId),
    queryFn: () => flowService.getAdmin(tournamentId as number),
    enabled: tournamentId !== null
  });
  const graph = graphQuery.data ?? null;
  // The kind/status pair names a message the catalogue carries for every lifecycle move and status; the key is built at
  // runtime, so it goes through an untyped view of the same translator.
  const tKey = t as unknown as (key: string, values?: Record<string, string>) => string;
  const stepLabel = (step: FlowStep) => tKey(`step.${step.node.kind}.${step.to}`, { name: step.node.name });
  const statusLabel = (node: PathNode) => tKey(`status.${node.kind}.${node.status}`);

  /** "First: 1. … 2. …" for these moves; null for none. */
  const describeSteps = (steps: readonly FlowStep[] | null | undefined): string | null =>
    steps?.length ? [t("needs"), ...steps.map((step, index) => `${index + 1}. ${stepLabel(step)}`)].join("\n") : null;

  /** The moves `nodeId → target` needs before itself, described; null when it needs none or no plan exists. */
  const prerequisites = (nodeId: number, target: string): string | null =>
    describeSteps(graph ? stepsTo(graph, nodeId, target)?.filter((step) => step.node.id !== nodeId) : null);

  /** The moves that bring `nodeId` to `target`, its own included; `[]` while the graph loads or when no plan exists. */
  const plan = (nodeId: number, target: string): FlowStep[] => (graph ? (stepsTo(graph, nodeId, target) ?? []) : []);

  /** Each move in order; the first refusal stops the run and is thrown. The tournament reads (graph included) refresh either way. */
  const run = async (steps: readonly FlowStep[]) => {
    try {
      for (const step of steps) await adminService.transitionNode(step.node.id, step.to as FlowNodeStatus);
    } finally {
      if (tournamentId !== null) invalidateTournamentWorkspace(queryClient, tournamentId);
    }
  };

  return { graph, stepLabel, statusLabel, describeSteps, prerequisites, plan, run };
}
