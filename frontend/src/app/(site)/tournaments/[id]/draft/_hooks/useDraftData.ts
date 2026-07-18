"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { tournamentQueryKeys } from "@/lib/tournament-query-keys";
import draftService from "@/services/draft.service";
import { realtimeClient } from "@/services/realtime.service";
import { useRealtimeStore } from "@/stores/realtime.store";
import { applyResourcePatch, registerRealtimeResource } from "@/services/realtime-patch";
import type {
  DraftBoard,
  DraftEventData,
  DraftPresenceState,
  DraftRole,
  DraftRoleEditRequest
} from "@/types/draft.types";
import type { RealtimeConnectionState, RealtimeEventEnvelope } from "@/types/realtime.types";

import {
  applyDraftEvent,
  draftInvalidationTargets,
  presenceFromEvent
} from "../_lib/draft-logic";

const MAX_PENDING_DRAFT_EVENTS = 100;
const EMPTY_DRAFT_PRESENCE: DraftPresenceState = { users: {}, anonymous_viewer_count: 0 };

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

const DRAFT_BOARD_RESOURCE = "draft.board";

// Register the draft board as a patchable realtime resource: draft WS events
// fold into the cached board in place instead of triggering a refetch. Mirrors
// the backend resource tag emitted by publish_draft_event.
registerRealtimeResource<DraftBoard, DraftEventData>(DRAFT_BOARD_RESOURCE, {
  queryKey: (tournamentId) => tournamentQueryKeys.draftBoard(tournamentId),
  reduce: (board, event) => applyDraftEvents(board, [event]),
});

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

export function useDraftFeasibilityQuery(sessionId: number | null, enabled = true) {
  return useQuery({
    queryKey: tournamentQueryKeys.draftFeasibility(sessionId ?? 0),
    queryFn: () => draftService.getFeasibility(sessionId!),
    enabled: enabled && sessionId != null && sessionId > 0
  });
}

export function useDraftPickOptionsQuery(pickId: number | null, enabled = true) {
  return useQuery({
    queryKey: tournamentQueryKeys.draftPickOptions(pickId ?? 0),
    queryFn: () => draftService.getPickOptions(pickId!),
    enabled: enabled && pickId != null && pickId > 0
  });
}

export function useDraftRealtime(
  tournamentId: number,
  board: DraftBoard | null
): { presence: DraftPresenceState; connectionState: RealtimeConnectionState } {
  const queryClient = useQueryClient();
  const topic = tournamentId ? `tournament:${tournamentId}:draft` : null;
  const queryKey = useMemo(
    () => tournamentQueryKeys.draftBoard(tournamentId),
    [tournamentId]
  );
  const pendingEventsRef = useRef<RealtimeEventEnvelope<DraftEventData>[]>([]);
  const resubscribedBaselineTopicRef = useRef<string | null>(null);
  const [presenceState, setPresenceState] = useState<{
    topic: string | null;
    value: DraftPresenceState;
  }>({ topic, value: EMPTY_DRAFT_PRESENCE });
  const presence = presenceState.topic === topic ? presenceState.value : EMPTY_DRAFT_PRESENCE;

  useEffect(() => {
    pendingEventsRef.current = [];
    resubscribedBaselineTopicRef.current = null;
  }, [topic]);

  useRealtimeTopic<DraftEventData>(
    topic,
    (event) => {
      if (event.event_type === "draft.presence") {
        setPresenceState({ topic, value: presenceFromEvent(event.data, event.occurred_at) });
        return;
      }

      const cachedBoard = queryClient.getQueryData<DraftBoard | null | undefined>(queryKey);
      const targets = draftInvalidationTargets(event.event_type);
      if (targets.includes("feasibility")) {
        queryClient.invalidateQueries({
          queryKey: tournamentQueryKeys.draftFeasibility(event.data.session_id)
        });
      }
      if (targets.includes("options")) {
        const affectedPickId = event.data.pick_id ?? cachedBoard?.current_pick?.id;
        if (affectedPickId != null) {
          queryClient.invalidateQueries({
            queryKey: tournamentQueryKeys.draftPickOptions(affectedPickId)
          });
        }
      }
      if (targets.includes("board")) {
        queryClient.invalidateQueries({ queryKey });
        return;
      }

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

      applyResourcePatch(queryClient, {
        resource: DRAFT_BOARD_RESOURCE,
        resourceId: tournamentId,
        event,
      });
    },
    [queryClient, queryKey, topic, tournamentId]
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
    for (const pendingEvent of pending) {
      applyResourcePatch(queryClient, {
        resource: DRAFT_BOARD_RESOURCE,
        resourceId: tournamentId,
        event: pendingEvent,
      });
    }
  }, [board, queryClient, queryKey, topic, tournamentId]);

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

  return { presence, connectionState };
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
    mutationFn: (v: {
      pickId: number;
      playerId: number;
      version: number;
      role: DraftRole;
      note: string;
    }) =>
      draftService.override(v.pickId, {
        player_id: v.playerId,
        expected_version: v.version,
        target_role: v.role,
        note: v.note
      }),
    onSettled: invalidate,
  });

  const lifecycle = useMutation({
    mutationFn: (v: { sessionId: number; action: DraftLifecycleAction }) =>
      draftService.lifecycle(tournamentId, v.sessionId, v.action),
    onSettled: invalidate,
  });

  const editPlayerRole = useMutation({
    mutationFn: (v: { sessionId: number; playerId: number; request: DraftRoleEditRequest }) =>
      draftService.editPlayerRole(v.sessionId, v.playerId, v.request),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.draftFeasibility(variables.sessionId)
      });
      queryClient.invalidateQueries({
        queryKey: tournamentQueryKeys.draftBoard(tournamentId)
      });
    }
  });

  return { makePick, autopick, override, lifecycle, editPlayerRole };
}
