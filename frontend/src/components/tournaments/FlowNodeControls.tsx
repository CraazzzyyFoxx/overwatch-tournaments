"use client";

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { StatusPill } from "@/components/kit/StatusPill";
import { Button } from "@/components/ui/button";
import type { Tone } from "@/components/ui/tone";
import { useFlowErrorNotifier } from "@/hooks/useFlowErrorNotifier";
import { nodesOfKind } from "@/lib/tournament/flow-nodes";
import { NODE_TRANSITIONS } from "@/lib/tournament/lifecycle";
import { invalidateTournamentWorkspace } from "@/lib/tournament/workspace-query-keys";
import adminService from "@/services/admin.service";
import type { FlowNodeStatus, TournamentFlowNode } from "@/types/flow.types";
import type { Tournament } from "@/types/tournament.types";

type ControlledKind = "registration" | "formation";
type ControlledStatus = "draft" | "open" | "check_in" | "closed" | "forming" | "completed";
type Move = "open" | "checkIn" | "close" | "reopen" | "startForming" | "backToDraft" | "complete";

/** What a button calls each `from>to` step of a registration or formation node, keyed by `NODE_TRANSITIONS`. */
const MOVES: Record<string, Move> = {
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

/** The moves with side effects beyond the node itself (announcements, frozen teams, ended check-in) ask first. */
const CONFIRMED: Partial<Record<Move, true>> = { open: true, checkIn: true, close: true, reopen: true, complete: true };
const WARNING: Partial<Record<Move, true>> = { close: true, complete: true };

const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  open: "success",
  check_in: "info",
  closed: "neutral",
  forming: "info",
  completed: "success"
};

/**
 * Whether a stage has started or the tournament is over: past that a registration or formation "Reopen" always answers
 * 409 `downstream_started`, so it is not offered. Only what the tournament read carries decides; a finer refusal
 * (a downstream node that left `draft`) still surfaces as its translated error.
 */
function playStarted(tournament: Tournament) {
  return (
    tournament.status === "completed" ||
    tournament.status === "archived" ||
    (tournament.flow_nodes ?? []).some(
      (node) => node.kind === "stage" && (node.status === "live" || node.status === "completed")
    )
  );
}

/**
 * Where an admin moves the registration and formation nodes (a stage moves from the Bracket tab): each node's label,
 * status and one button per move `NODE_TRANSITIONS` allows from there, every one a `POST /admin/flow-nodes/{id}/transition`.
 * A node is named by its own name only when the tournament has several of its kind; a lone default node reads as its kind.
 * Moves that announce, freeze or end something go through a confirmation. `node` limits it to that one node, for a screen
 * that embeds it (the hub header, the formation tools). Without `canUpdate` (`tournament.update`) only the status shows.
 */
export function FlowNodeControls({
  tournament,
  node,
  canUpdate
}: Readonly<{ tournament: Tournament; node?: TournamentFlowNode; canUpdate: boolean }>) {
  const t = useTranslations("common.flowNode");
  const queryClient = useQueryClient();
  const notifyFlowError = useFlowErrorNotifier();
  const [moving, setMoving] = useState<number | null>(null);
  const [asking, setAsking] = useState<{ node: TournamentFlowNode; target: FlowNodeStatus; move: Move } | null>(null);

  const mutation = useMutation({
    mutationFn: ({ nodeId, status }: { nodeId: number; status: FlowNodeStatus }) =>
      adminService.transitionNode(nodeId, status),
    onMutate: ({ nodeId }) => setMoving(nodeId),
    onSettled: () => {
      setMoving(null);
      setAsking(null);
    },
    onSuccess: () => invalidateTournamentWorkspace(queryClient, tournament.id),
    onError: (error) => notifyFlowError(error, t("error"))
  });

  const nodes = (
    node ? [node] : [...nodesOfKind(tournament, "registration"), ...nodesOfKind(tournament, "formation")]
  ).filter((current) => current.kind === "registration" || current.kind === "formation");
  if (nodes.length === 0) return null;

  const started = playStarted(tournament);
  const label = (current: TournamentFlowNode) =>
    nodesOfKind(tournament, current.kind as ControlledKind).length > 1
      ? current.name
      : t(`kind.${current.kind as ControlledKind}`);
  const request = (current: TournamentFlowNode, target: FlowNodeStatus, move: Move) =>
    CONFIRMED[move]
      ? setAsking({ node: current, target, move })
      : mutation.mutate({ nodeId: current.id, status: target });

  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      {nodes.map((current) => {
        const kind = current.kind as ControlledKind;
        const moves = canUpdate ? (NODE_TRANSITIONS[kind][current.status] ?? []) : [];
        return (
          <div key={current.id} className="flex items-center gap-2">
            <span className="text-caption font-medium">{label(current)}</span>
            <StatusPill tone={STATUS_TONE[current.status] ?? "neutral"}>
              {t(`status.${current.status as ControlledStatus}`)}
            </StatusPill>
            {moves.flatMap((target) => {
              const move = MOVES[`${kind}.${current.status}>${target}`];
              if (move === "reopen" && started) return [];
              return [
                <Button
                  key={target}
                  variant="outline"
                  size="sm"
                  disabled={moving === current.id}
                  onClick={() => request(current, target as FlowNodeStatus, move)}
                >
                  {t(move)}
                </Button>
              ];
            })}
          </div>
        );
      })}

      {asking ? (
        <ConfirmDialog
          open
          onOpenChange={(open) => !open && setAsking(null)}
          intent={{
            title: t(`confirm.${asking.move as "open"}.title`, { name: label(asking.node) }),
            description: t(`confirm.${asking.move as "open"}.description`, { name: label(asking.node) }),
            confirmLabel: t(asking.move),
            tone: WARNING[asking.move] ? "warning" : "neutral"
          }}
          pending={mutation.isPending}
          onConfirm={() => mutation.mutate({ nodeId: asking.node.id, status: asking.target })}
        />
      ) : null}
    </div>
  );
}
