"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo } from "react";

import {
  applyTournamentRealtimeCatchUp,
  applyTournamentRealtimeUpdate,
  createLeadingCoalescer,
  type TournamentChangedReason,
} from "@/hooks/tournamentRealtime.helpers";
import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";

type TournamentRealtimePayload = {
  tournament_id?: number;
  reason?: TournamentChangedReason;
};

type UseTournamentRealtimeOptions = {
  tournamentId: number | null | undefined;
  workspaceId?: number | null;
  onUpdate?: (reason: TournamentChangedReason) => void;
  onStructureChanged?: () => void;
};

const CATCH_UP_COALESCE_MS = 100;

export function useTournamentRealtime({
  tournamentId,
  workspaceId,
  onUpdate,
  onStructureChanged,
}: UseTournamentRealtimeOptions): void {
  const queryClient = useQueryClient();

  const topic = tournamentId ? `tournament:${tournamentId}:bracket` : null;
  const catchUp = useMemo(
    () =>
      createLeadingCoalescer(() => {
        if (tournamentId) {
          applyTournamentRealtimeCatchUp(queryClient, tournamentId, workspaceId);
        }
      }, CATCH_UP_COALESCE_MS),
    [queryClient, tournamentId, workspaceId],
  );

  useEffect(() => () => catchUp.cancel(), [catchUp]);

  useRealtimeTopic<TournamentRealtimePayload>(
    topic,
    (event) => {
      if (
        !tournamentId ||
        event.event_type !== "tournament.updated" ||
        event.data.tournament_id !== tournamentId ||
        (event.data.reason !== "bracket_changed" &&
          event.data.reason !== "results_changed" &&
          event.data.reason !== "structure_changed")
      ) {
        return;
      }

      applyTournamentRealtimeUpdate(
        queryClient,
        tournamentId,
        workspaceId,
        event.data.reason
      );
      onUpdate?.(event.data.reason);
      if (event.data.reason === "structure_changed") {
        onStructureChanged?.();
      }
    },
    [],
    () => {
      catchUp.schedule();
    },
  );
}
