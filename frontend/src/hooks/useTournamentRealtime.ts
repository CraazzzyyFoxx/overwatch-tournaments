"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";

import {
  applyTournamentRealtimeCatchUp,
  applyTournamentRealtimeUpdate,
  type BracketFamilyReason,
  strongerTournamentReason,
  type TournamentChangedReason,
} from "@/hooks/tournamentRealtime.helpers";
import { useRealtimeCoalescedRefetch } from "@/hooks/useRealtimeCoalescedRefetch";

type TournamentRealtimePayload = {
  tournament_id?: number;
  reason?: TournamentChangedReason;
};

type UseTournamentRealtimeOptions = {
  tournamentId: number | null | undefined;
  workspaceId?: number | null;
  onUpdate?: (reason: TournamentChangedReason) => void;
  onStructureChanged?: () => void;
  // The public overview query's own key (slug/legacy id) when it differs
  // from tournamentId -- see tournamentRealtime.helpers.getTournamentRealtimeUpdatePlan.
  // Defaults to tournamentId for every other caller (admin pages).
  detailRef?: string | number;
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
  detailRef,
}: UseTournamentRealtimeOptions): void {
  const queryClient = useQueryClient();
  const resolvedDetailRef = detailRef ?? tournamentId ?? undefined;

  const topic = tournamentId ? `tournament:${tournamentId}:bracket` : null;

  // Strongest bracket-family reason accumulated within the current debounce
  // window, plus a separate flag for registration_changed — its plan is
  // disjoint from the bracket family's, so it can't be folded into the same
  // total-order scalar (see BracketFamilyReason).
  const pendingReasonRef = useRef<BracketFamilyReason | null>(null);
  const pendingRegistrationChangeRef = useRef(false);
  // Same story for the form: its plan is one key and overlaps nothing, so it
  // gets its own flag rather than being folded into either of the above.
  const pendingFormChangeRef = useRef(false);

  // Dropped on topic change (a different tournamentId) or unmount -- a
  // reason/flag pending for one tournament's topic must never leak into the
  // next one's flush.
  useEffect(() => {
    return () => {
      pendingReasonRef.current = null;
      pendingRegistrationChangeRef.current = false;
      pendingFormChangeRef.current = false;
    };
  }, [topic]);

  useRealtimeCoalescedRefetch<TournamentRealtimePayload>(topic, {
    minDelayMs: REALTIME_REFETCH_MIN_DELAY_MS,
    jitterMs: REALTIME_REFETCH_JITTER_MS,
    catchUpMs: CATCH_UP_COALESCE_MS,
    onEvent: (event, schedule) => {
      if (
        !tournamentId ||
        event.event_type !== "tournament.updated" ||
        event.data.tournament_id !== tournamentId
      ) {
        return;
      }
      const reason = event.data.reason;
      if (reason === "registration_changed") {
        pendingRegistrationChangeRef.current = true;
        schedule();
        return;
      }
      if (reason === "registration_form_changed") {
        pendingFormChangeRef.current = true;
        schedule();
        return;
      }
      if (
        reason !== "bracket_changed" &&
        reason !== "results_changed" &&
        reason !== "structure_changed"
      ) {
        return;
      }

      pendingReasonRef.current = strongerTournamentReason(pendingReasonRef.current, reason);
      schedule();
    },
    // The (re)subscribe/reconnect catch-up plan is broader than a normal
    // flush's -- it re-fetches everything, not just what the accumulated
    // reason implies -- so it runs independently of pendingReasonRef/
    // pendingRegistrationChangeRef, exactly as it did before this refactor.
    onCatchUp: () => {
      if (tournamentId) {
        applyTournamentRealtimeCatchUp(queryClient, tournamentId, workspaceId, resolvedDetailRef);
      }
    },
    onFlush: () => {
      const reason = pendingReasonRef.current;
      const hasRegistrationChange = pendingRegistrationChangeRef.current;
      const hasFormChange = pendingFormChangeRef.current;
      pendingReasonRef.current = null;
      pendingRegistrationChangeRef.current = false;
      pendingFormChangeRef.current = false;
      if (!tournamentId || (!reason && !hasRegistrationChange && !hasFormChange)) {
        return;
      }
      if (reason) {
        applyTournamentRealtimeUpdate(queryClient, tournamentId, workspaceId, reason, undefined, resolvedDetailRef);
        onUpdate?.(reason);
        if (reason === "structure_changed") {
          onStructureChanged?.();
        }
      }
      // structure_changed's plan already covers the registration keys — skip
      // the redundant second refetch when both landed in the same window.
      if (hasRegistrationChange && reason !== "structure_changed") {
        applyTournamentRealtimeUpdate(queryClient, tournamentId, workspaceId, "registration_changed", undefined, resolvedDetailRef);
        onUpdate?.("registration_changed");
      }
      // Unconditional: no other reason's plan carries the form key, so unlike
      // registration_changed there is nothing for structure_changed to
      // supersede here.
      if (hasFormChange) {
        applyTournamentRealtimeUpdate(queryClient, tournamentId, workspaceId, "registration_form_changed", undefined, resolvedDetailRef);
        onUpdate?.("registration_form_changed");
      }
    },
  });
}
