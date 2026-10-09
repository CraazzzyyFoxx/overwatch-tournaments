"use client";

import { useQuery } from "@tanstack/react-query";

import { useBalancerTournamentId } from "@/app/balancer/components/useBalancerTournamentId";
import { resolveToolState, type ToolContextStatus } from "@/app/balancer/tool-context";
import { useEntityWorkspace } from "@/hooks/useEntityWorkspace";
import balancerAdminService from "@/services/balancer-admin.service";
import { useWorkspaceStore } from "@/stores/workspace.store";
import type { BalancerTournamentSummary } from "@/types/balancer-admin.types";
import { balancerQueryKeys } from "@/lib/balancer/query-keys";

export interface ToolContext {
  status: ToolContextStatus;
  summary: BalancerTournamentSummary | null;
}

/**
 * Resolves the balancer tool's tournament context from `?tournament=` (D29).
 *
 * The summary resolves ownership server-side. Object-local requests wait for
 * runtime entity context, without overwriting the saved viewing preference.
 */
export function useToolContext(): ToolContext {
  const tournamentId = useBalancerTournamentId();
  const query = useQuery({
    queryKey: balancerQueryKeys.tournamentSummary(tournamentId),
    queryFn: () => balancerAdminService.getTournamentSummary(tournamentId as number),
    enabled: tournamentId != null,
    // Errors are terminal states (forbidden / pointer screen) — surface them
    // immediately instead of spinning through retries.
    retry: false,
    staleTime: 60_000
  });
  const summary = query.data ?? null;

  useEntityWorkspace(summary?.workspace_id);
  const entityWorkspaceId = useWorkspaceStore((state) => state.entityWorkspaceId);
  const aligned = summary == null || entityWorkspaceId === summary.workspace_id;

  const status = resolveToolState(tournamentId, query);
  return { status: status === "ready" && !aligned ? "loading" : status, summary };
}
