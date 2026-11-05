"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import type { Tone } from "@/components/ui/tone";
import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import { NODE_TRANSITIONS } from "@/lib/tournament/lifecycle";
import { notify } from "@/lib/notify";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import adminService from "@/services/admin.service";
import type { FlowNodeStatus, TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

type ControlledKind = "registration" | "formation";
type ControlledStatus = "draft" | "open" | "check_in" | "closed" | "forming" | "completed";

/** What a button calls each `from>to` step of a registration or formation node, keyed by `NODE_TRANSITIONS`. */
const MOVES: Record<string, "open" | "checkIn" | "close" | "reopen" | "startForming" | "backToDraft" | "complete"> = {
  "registration.draft>open": "open",
  "registration.open>check_in": "checkIn",
  "registration.open>closed": "close",
  "registration.check_in>closed": "close",
  "registration.closed>open": "reopen",
  "formation.draft>forming": "startForming",
  "formation.forming>draft": "backToDraft",
  "formation.forming>completed": "complete",
  "formation.completed>forming": "reopen"
};

const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  open: "success",
  check_in: "info",
  closed: "neutral",
  forming: "info",
  completed: "success"
};

/**
 * Where an admin moves the registration and formation nodes (a stage moves from the Bracket tab): each node's name,
 * status and one button per move `NODE_TRANSITIONS` allows from there, every one a `POST /admin/flow-nodes/{id}/transition`.
 * `node` limits it to that one node, for a flow inspector that embeds it. Needs `tournament.update`.
 */
export function FlowNodeControls({
  tournament,
  node,
  canUpdate
}: Readonly<{ tournament: Tournament; node?: TournamentFlowNode; canUpdate: boolean }>) {
  const t = useTranslations("adminTournaments.nodeControls");
  const queryClient = useQueryClient();
  const [moving, setMoving] = useState<number | null>(null);

  const mutation = useMutation({
    mutationFn: ({ nodeId, status }: { nodeId: number; status: FlowNodeStatus }) =>
      adminService.transitionNode(nodeId, status),
    onMutate: ({ nodeId }) => setMoving(nodeId),
    onSettled: () => setMoving(null),
    onSuccess: () => invalidateTournamentWorkspace(queryClient, tournament.id),
    onError: (error) => notify.apiError(error, { title: t("error") })
  });

  const nodes = node ? [node] : [...nodesOfKind(tournament, "registration"), ...nodesOfKind(tournament, "formation")];
  if (!canUpdate || nodes.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {nodes.map((current) => {
        const kind = current.kind as ControlledKind;
        const moves = NODE_TRANSITIONS[kind][current.status] ?? [];
        return (
          <div key={current.id} className="flex items-center gap-2">
            <span className="text-caption font-medium">{current.name}</span>
            <StatusPill tone={STATUS_TONE[current.status] ?? "neutral"}>{t(`status.${current.status as ControlledStatus}`)}</StatusPill>
            {moves.map((target) => (
              <Button
                key={target}
                variant="outline"
                size="sm"
                disabled={moving === current.id}
                onClick={() => mutation.mutate({ nodeId: current.id, status: target as FlowNodeStatus })}
              >
                {t(MOVES[`${kind}.${current.status}>${target}`])}
              </Button>
            ))}
          </div>
        );
      })}
    </div>
  );
}
