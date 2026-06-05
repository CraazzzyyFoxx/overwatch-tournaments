"use client";

import { useEffect, useMemo, useRef } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";
import { realtimeClient } from "@/services/realtime.service";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { DraftBoard, DraftEventData, DraftRole } from "@/types/draft.types";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

import { applyDraftEvent } from "../_lib/draft-logic";

const MAX_PENDING_DRAFT_EVENTS = 100;

function applyDraftEvents(
  board: DraftBoard,
  events: readonly RealtimeEventEnvelope<DraftEventData>[]
): DraftBoard {
  let next = board;
  let lastEventId = board.last_event_id ?? 0;

  for (const event of [...events].sort((a, b) => a.event_id - b.event_id)) {
    if (event.event_id <= lastEventId) {
      continue;
    }
    next = applyDraftEvent(next, event);
    lastEventId = event.event_id;
  }

  return lastEventId === (board.last_event_id ?? 0)
    ? next
    : { ...next, last_event_id: lastEventId };
}

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

export function useDraftRealtime(tournamentId: number, board: DraftBoard | null): void {
  const queryClient = useQueryClient();
  const topic = tournamentId ? `tournament:${tournamentId}:draft` : null;
  const queryKey = useMemo(
    () => tournamentQueryKeys.draftBoard(tournamentId),
    [tournamentId]
  );
  const pendingEventsRef = useRef<RealtimeEventEnvelope<DraftEventData>[]>([]);
  const resubscribedBaselineTopicRef = useRef<string | null>(null);

  useEffect(() => {
    pendingEventsRef.current = [];
    resubscribedBaselineTopicRef.current = null;
  }, [topic]);

  useRealtimeTopic<DraftEventData>(
    topic,
    (event) => {
      if (event.event_type === "draft.presence") return;
      if (event.event_type === "draft.rollback" || event.event_type === "draft.session_updated") {
        queryClient.invalidateQueries({ queryKey });
        return;
      }

      const cachedBoard = queryClient.getQueryData<DraftBoard | null | undefined>(queryKey);
      if (!cachedBoard) {
        const pending = pendingEventsRef.current;
        if (!pending.some((pendingEvent) => pendingEvent.event_id === event.event_id)) {
          pending.push(event);
          pending.sort((a, b) => a.event_id - b.event_id);
          pendingEventsRef.current = pending.slice(-MAX_PENDING_DRAFT_EVENTS);
        }
        queryClient.invalidateQueries({ queryKey });
        return;
      }

      queryClient.setQueryData<DraftBoard | null | undefined>(
        queryKey,
        (currentBoard) => (currentBoard ? applyDraftEvents(currentBoard, [event]) : currentBoard)
      );
    },
    [queryClient, queryKey]
  );

  useEffect(() => {
    if (!topic || !board) {
      return;
    }

    useRealtimeStore.getState().setLastEventId(topic, board.last_event_id ?? 0);
    if (resubscribedBaselineTopicRef.current !== topic) {
      realtimeClient.resubscribe(topic);
      resubscribedBaselineTopicRef.current = topic;
    }

    const pending = pendingEventsRef.current;
    if (pending.length === 0) {
      return;
    }

    pendingEventsRef.current = [];
    queryClient.setQueryData<DraftBoard | null | undefined>(
      queryKey,
      (currentBoard) => (currentBoard ? applyDraftEvents(currentBoard, pending) : currentBoard)
    );
  }, [board, queryClient, queryKey, topic]);

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

export type DraftLifecycleAction = "start" | "pause" | "resume" | "cancel" | "export" | "rollback";

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
