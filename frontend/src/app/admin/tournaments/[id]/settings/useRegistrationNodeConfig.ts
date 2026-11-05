"use client";

import { useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { useScopedSettingsForm } from "@/components/kit/useScopedSettingsForm";
import { registrationNodeConfig, type RegistrationNodeConfig } from "@/lib/tournament/flow-nodes";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import flowService from "@/services/flow.service";
import type { TournamentFlowNode } from "@/types/flow.types";

/**
 * Form state of the intake settings stored in one registration node's config. A section edits a subset of the fields
 * and the save sends the whole config (the node upsert is a full replace of `config`), so another section's fields
 * are never reset. Remount per node (`key={node.id}`): a pending edit belongs to the node it was typed into.
 */
export function useRegistrationNodeConfig(tournamentId: number, node: TournamentFlowNode | null) {
  const client = useQueryClient();
  // `null` for a screen that needs the settings only on some tournaments: the form stays empty.
  const baseline = useMemo(() => (node ? registrationNodeConfig(node) : null), [node]);
  return useScopedSettingsForm<RegistrationNodeConfig, Partial<RegistrationNodeConfig>>({
    baseline,
    toPayload: (form, base) =>
      Object.fromEntries(
        Object.entries(form).filter(([key, value]) => value !== base[key as keyof RegistrationNodeConfig])
      ),
    submit: (payload) =>
      flowService.applyChanges(tournamentId, {
        nodes: [{ id: node!.id, kind: node!.kind, name: node!.name, config: { ...node!.config, ...payload } }]
      }),
    onSaved: () => void invalidateTournamentWorkspace(client, tournamentId)
  });
}
