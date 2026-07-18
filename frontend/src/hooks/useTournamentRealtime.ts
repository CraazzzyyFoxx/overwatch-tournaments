"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import {
  applyTournamentRealtimeCatchUp,
  applyTournamentRealtimeUpdate,
  type Coalescer,
  createLeadingCoalescer,
  createTrailingCoalescer,
  strongerTournamentReason,
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

// A single bracket move fans a realtime event to every spectator at once, and
// each move emits 2-3 waves (bracket_changed immediately, then results_changed
// after the standings recompute, plus any follow-up recalcs). Applied naively
// that is a synchronized bundle-refetch herd that spikes backend/VPS load.
//
// So instead of refetching on every event inline we debounce with a per-client
// jittered delay in [MIN, MIN+JITTER): (1) the waves of one move collapse into a
// single refetch that applies the broadest reason seen (their update plans are
// supersets — see strongerTournamentReason), and (2) each client fires at a
// different random offset, so the herd's refetches spread out in time instead of
// landing in the same instant. The small added latency is an acceptable trade
// for a flat load curve on standings/bracket reads.
const REALTIME_REFETCH_MIN_DELAY_MS = 250;
const REALTIME_REFETCH_JITTER_MS = 2500;

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

  // Latest options + queryClient read at flush time (the flush runs from a timer,
  // not render, so it must not close over stale values).
  const stateRef = useRef({ tournamentId, workspaceId, onUpdate, onStructureChanged, queryClient });
  useEffect(() => {
    stateRef.current = { tournamentId, workspaceId, onUpdate, onStructureChanged, queryClient };
  });

  // Strongest reason accumulated within the current debounce window.
  const pendingReasonRef = useRef<TournamentChangedReason | null>(null);

  // The debounced flush is created in an effect (not render) so the coalescer's
  // ref-reading callback is never constructed during render, and the per-client
  // jitter is drawn here rather than in render. Rebuilt per topic; the cleanup
  // drops any pending flush and stale reason.
  const updatesRef = useRef<Coalescer | null>(null);
  useEffect(() => {
    const delay =
      REALTIME_REFETCH_MIN_DELAY_MS + Math.floor(Math.random() * REALTIME_REFETCH_JITTER_MS);
    const coalescer = createTrailingCoalescer(() => {
      const reason = pendingReasonRef.current;
      pendingReasonRef.current = null;
      const {
        tournamentId: id,
        workspaceId: ws,
        onUpdate: notify,
        onStructureChanged: onStructure,
        queryClient: client,
      } = stateRef.current;
      if (!reason || !id) {
        return;
      }
      applyTournamentRealtimeUpdate(client, id, ws, reason);
      notify?.(reason);
      if (reason === "structure_changed") {
        onStructure?.();
      }
    }, delay);
    updatesRef.current = coalescer;
    return () => {
      coalescer.cancel();
      updatesRef.current = null;
      pendingReasonRef.current = null;
    };
  }, [topic]);

  useRealtimeTopic<TournamentRealtimePayload>(
    topic,
    (event) => {
      if (
        !tournamentId ||
        event.event_type !== "tournament.updated" ||
        event.data.tournament_id !== tournamentId
      ) {
        return;
      }
      const reason = event.data.reason;
      if (
        reason !== "bracket_changed" &&
        reason !== "results_changed" &&
        reason !== "structure_changed"
      ) {
        return;
      }

      pendingReasonRef.current = strongerTournamentReason(pendingReasonRef.current, reason);
      updatesRef.current?.schedule();
    },
    [],
    () => {
      catchUp.schedule();
    },
  );
}
