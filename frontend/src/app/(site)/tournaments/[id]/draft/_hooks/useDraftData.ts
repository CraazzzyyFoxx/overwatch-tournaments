"use client";

import { useEffect, useRef } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { DraftBoard, DraftEventData, DraftRole } from "@/types/draft.types";

import { applyDraftEvent } from "../_lib/draft-logic";

export function useDraftBoardQuery(tournamentId: number) {
  return useQuery({
    queryKey: tournamentQueryKeys.draftBoard(tournamentId),
    queryFn: () => draftService.getTournamentBoard(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
    // Realtime drives freshness; a slow poll while live is a safety net.
    refetchInterval: (query) =>
      query.state.data?.session.status === "live" ? 30_000 : false,
  });
}

export function useDraftRealtime(tournamentId: number): void {
  const queryClient = useQueryClient();
  const topic = tournamentId ? `tournament:${tournamentId}:draft` : null;

  useRealtimeTopic<DraftEventData>(
    topic,
    (event) => {
      if (event.event_type === "draft.presence") return;
      queryClient.setQueryData<DraftBoard | null | undefined>(
        tournamentQueryKeys.draftBoard(tournamentId),
        (board) => (board ? applyDraftEvent(board, event) : board)
      );
    },
    [queryClient, tournamentId]
  );

  // On reconnect, the client replays from the cursor; refetch the snapshot as a
  // safety net so the board converges even after a long disconnect.
  const connectionState = useRealtimeStore((s) => s.connectionState);
  const prev = useRef(connectionState);
  useEffect(() => {
    if (prev.current === "reconnecting" && connectionState === "connected") {
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.draftBoard(tournamentId),
      });
    }
    prev.current = connectionState;
  }, [connectionState, queryClient, tournamentId]);
}

export type DraftLifecycleAction = "start" | "pause" | "resume" | "cancel" | "export";

export function useDraftMutations(tournamentId: number) {
  const queryClient = useQueryClient();
  const invalidate = () =>
    queryClient.invalidateQueries({
      queryKey: tournamentQueryKeys.draftBoard(tournamentId),
    });

  const makePick = useMutation({
    mutationFn: (v: { pickId: number; playerId: number; version: number; role?: DraftRole | null }) =>
      draftService.select(v.pickId, {
        player_id: v.playerId,
        expected_version: v.version,
        target_role: v.role ?? null,
      }),
    onSettled: invalidate,
  });

  const autopick = useMutation({
    mutationFn: (v: { pickId: number; version: number }) =>
      draftService.autopick(v.pickId, { expected_version: v.version, reason: "admin" }),
    onSettled: invalidate,
  });

  const override = useMutation({
    mutationFn: (v: { pickId: number; playerId: number; version: number }) =>
      draftService.override(v.pickId, { player_id: v.playerId, expected_version: v.version }),
    onSettled: invalidate,
  });

  const lifecycle = useMutation({
    mutationFn: (v: { sessionId: number; action: DraftLifecycleAction }) =>
      draftService.lifecycle(tournamentId, v.sessionId, v.action),
    onSettled: invalidate,
  });

  return { makePick, autopick, override, lifecycle };
}
