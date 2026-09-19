"use client";

import Link from "next/link";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { BarChart3, CheckCircle2, Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { notify } from "@/lib/notify";
import adminService from "@/services/admin.service";
import type { Tournament } from "@/types/tournament.types";
import { TournamentStatusControl } from "./TournamentStatusControl";
import { invalidateTournamentWorkspace } from "@/lib/tournament-workspace-query-keys";

/**
 * The hub header's action cluster.
 *
 * The status control moved here from `PhaseStepper`: the stepper says where the
 * tournament is, the header is where you change it. Keeping the control inside
 * the stepper made a read-only progress indicator the only place a phase could
 * be advanced from, three screens deep in the Overview tab.
 */
export function TournamentHubActions({
  tournament,
  tournamentId,
  canReadAnalytics,
  canUpdateTournament,
  canToggleFinished
}: Readonly<{
  tournament: Tournament;
  tournamentId: number;
  canReadAnalytics: boolean;
  /** `tournament.update` — the grant the status RPC checks. */
  canUpdateTournament: boolean;
  canToggleFinished: boolean;
}>) {
  const queryClient = useQueryClient();

  const toggleFinishedMutation = useMutation({
    mutationFn: () => adminService.toggleTournamentFinished(tournamentId),
    onSuccess: () => {
      invalidateTournamentWorkspace(queryClient, tournamentId);
      notify.success(
        tournament.is_finished ? "Tournament reopened" : "Tournament marked as finished"
      );
    }
  });

  return (
    <>
      {canReadAnalytics ? (
        <Button asChild variant="outline" size="sm">
          <Link href={`/tournaments/analytics?tournamentId=${tournament.id}`}>
            <BarChart3 className="size-4" aria-hidden />
            Open analytics
          </Link>
        </Button>
      ) : null}
      {canUpdateTournament ? <TournamentStatusControl tournament={tournament} /> : null}
      {canToggleFinished ? (
        <Button
          size="sm"
          onClick={() => toggleFinishedMutation.mutate()}
          disabled={toggleFinishedMutation.isPending}
        >
          {toggleFinishedMutation.isPending ? (
            <Loader2 className="size-4 animate-spin" aria-hidden />
          ) : (
            <CheckCircle2 className="size-4" aria-hidden />
          )}
          {tournament.is_finished ? "Reopen" : "Mark finished"}
        </Button>
      ) : null}
    </>
  );
}
