"use client";

import { useId, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { ConfirmDialog } from "@/components/kit/ConfirmDialog";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from "@/components/ui/select";
import { usePermissions } from "@/hooks/usePermissions";
import {
  TOURNAMENT_PHASES,
  TOURNAMENT_STATUS_LABELS,
  VALID_TRANSITIONS
} from "@/lib/tournament-lifecycle";
import adminService from "@/services/admin.service";
import type { Tournament, TournamentStatus } from "@/types/tournament.types";
import { invalidateTournamentWorkspace } from "@/lib/tournament-workspace-query-keys";

/**
 * The one place the tournament's status is changed.
 *
 * It used to be three things side by side — a badge, "→ Next" buttons and a
 * superuser-only Select with its own "Set status" button — beside the status
 * pill the hub header already carries. Now it is the Select alone: its value
 * IS the current status, so nothing else needs to restate it. Picking a value
 * asks for confirmation (a status change moves the public page), then commits.
 *
 * Every `tournament.update` holder gets the transitions the state machine
 * allows; a superuser additionally gets every other status, sent with `force`.
 */
export function TournamentStatusControl({ tournament }: Readonly<{ tournament: Tournament }>) {
  const queryClient = useQueryClient();
  const { isSuperuser } = usePermissions();
  const [pendingStatus, setPendingStatus] = useState<TournamentStatus | null>(null);
  const selectId = useId();

  const allowed = VALID_TRANSITIONS[tournament.status];
  const options = isSuperuser
    ? TOURNAMENT_PHASES
    : TOURNAMENT_PHASES.filter(
        (status) => status === tournament.status || allowed.includes(status)
      );

  const mutation = useMutation({
    mutationFn: (status: TournamentStatus) =>
      adminService.transitionTournamentStatus(tournament.id, {
        status,
        force: !allowed.includes(status)
      }),
    onSuccess: () => {
      setPendingStatus(null);
      invalidateTournamentWorkspace(queryClient, tournament.id);
    }
  });

  return (
    <>
      <Label htmlFor={selectId} className="sr-only">
        Tournament status
      </Label>
      <Select
        value={tournament.status}
        onValueChange={(value) => {
          if (value !== tournament.status) setPendingStatus(value as TournamentStatus);
        }}
      >
        <SelectTrigger id={selectId} className="h-8 w-[160px]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((status) => (
            <SelectItem key={status} value={status}>
              {TOURNAMENT_STATUS_LABELS[status]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      {mutation.isError && (
        <span role="alert" className="text-sm text-danger">
          Unable to change the status: {(mutation.error as Error).message}
        </span>
      )}

      <ConfirmDialog
        open={pendingStatus !== null}
        onOpenChange={(open) => (open ? undefined : setPendingStatus(null))}
        intent={{
          title: pendingStatus
            ? `Set status to ${TOURNAMENT_STATUS_LABELS[pendingStatus]}?`
            : "Change status?",
          description:
            pendingStatus && !allowed.includes(pendingStatus)
              ? `${TOURNAMENT_STATUS_LABELS[tournament.status]} does not normally lead to ${TOURNAMENT_STATUS_LABELS[pendingStatus]}; this bypasses the state machine. Automatic phase transitions are switched off either way.`
              : "The public tournament page follows the status. Automatic phase transitions are switched off after a manual change.",
          confirmLabel: pendingStatus
            ? `Set ${TOURNAMENT_STATUS_LABELS[pendingStatus]}`
            : "Set status",
          tone: pendingStatus && !allowed.includes(pendingStatus) ? "warning" : "neutral"
        }}
        pending={mutation.isPending}
        onConfirm={() => {
          if (pendingStatus) mutation.mutate(pendingStatus);
        }}
      />
    </>
  );
}
