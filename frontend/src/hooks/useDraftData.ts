"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";
import userService from "@/services/user.service";
import { realtimeClient } from "@/services/realtime.service";
import { useRealtimeStore } from "@/stores/realtime.store";
import { applyResourcePatch, registerRealtimeResource } from "@/services/realtime-patch";
import type {
  DraftBoard,
  DraftEventData,
  DraftPresenceState,
  DraftRole,
  DraftRoleEditRequest,
  DraftTeamQueueResponse
} from "@/types/draft.types";
import type { RealtimeConnectionState, RealtimeEventEnvelope } from "@/types/realtime.types";

import { applyDraftEvent, presenceFromEvent } from "@/lib/draft/logic";

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
registerRealtimeResource<DraftBoard, DraftEventData>(DRAFT_BOARD_RESOURCE, (board, event) =>
  applyDraftEvents(board, [event]),
);

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

/**
 * The server's fit for one team. Only the seats that act for a team read it
 * (a captain for their own, an admin for the team on the clock), so it stays
 * disabled until the caller knows which team that is.
 */
export function useDraftTeamFitQuery(sessionId: number | null, teamId: number | null, enabled = true) {
  return useQuery({
    queryKey: tournamentQueryKeys.draftTeamFit(sessionId ?? 0, teamId ?? 0),
    queryFn: () => draftService.getTeamFit(sessionId!, teamId!),
    enabled: enabled && sessionId != null && teamId != null
  });
}

/**
 * A captain's private pick queue ("My list"). The order is the autopick's
 * priority, so edits are optimistic: the list moves under the pointer and the
 * server's answer (which also re-derives the autopick preview) replaces it.
 */
export function useDraftTeamQueue(sessionId: number | null, teamId: number | null) {
  const queryClient = useQueryClient();
  const queryKey = tournamentQueryKeys.draftTeamQueue(sessionId ?? 0, teamId ?? 0);
  const query = useQuery({
    queryKey,
    queryFn: () => draftService.getTeamQueue(sessionId!, teamId!),
    enabled: sessionId != null && teamId != null
  });
  const setQueue = useMutation({
    mutationFn: (playerIds: number[]) => draftService.setTeamQueue(sessionId!, teamId!, playerIds),
    onMutate: async (playerIds) => {
      await queryClient.cancelQueries({ queryKey });
      const previous = queryClient.getQueryData<DraftTeamQueueResponse>(queryKey);
      queryClient.setQueryData<DraftTeamQueueResponse>(queryKey, (current) => ({
        team_id: teamId!,
        autopick_preview: current?.autopick_preview ?? null,
        player_ids: playerIds
      }));
      return { previous };
    },
    onError: (_error, _playerIds, context) => {
      if (context?.previous) queryClient.setQueryData(queryKey, context.previous);
    },
    onSuccess: (response) => queryClient.setQueryData(queryKey, response)
  });
  return { query, playerIds: query.data?.player_ids ?? EMPTY_QUEUE, setQueue };
}

const EMPTY_QUEUE: number[] = [];

/** Organizer journal; fetched only while the organizer has it open. */
export function useDraftJournalQuery(sessionId: number | null, enabled: boolean) {
  return useQuery({
    queryKey: tournamentQueryKeys.draftJournal(sessionId ?? 0),
    queryFn: () => draftService.getJournal(sessionId!),
    enabled: enabled && sessionId != null
  });
}

/** Career stats for the player card; keyed by the domain user id, cached across sessions. */
export function useDraftPlayerCardQuery(userId: number | null) {
  return useQuery({
    queryKey: tournamentQueryKeys.draftPlayerCard(userId ?? 0),
    queryFn: () => userService.getDraftCard(userId!),
    enabled: userId != null,
    staleTime: 5 * 60_000
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
      // The draft topic is DATA only: nothing here evicts another consumer's
      // cache. What a draft genuinely stales for everyone else — the
      // materialized export — arrives as a tournament invalidation.
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

      applyResourcePatch(queryClient, {
        resource: DRAFT_BOARD_RESOURCE,
        queryKey,
        event,
      });

      // Two derived reads the patch cannot fold in: feasibility is keyed by
      // SESSION id, which does not change when a pick lands, and pick options
      // by pick id, which a role edit changes without advancing the pick.
      // Deliberately handled here instead of through the invalidation
      // vocabulary: no server cache holds either of them and no other consumer
      // has an opinion about them, so there is nothing for a shared resource
      // name to keep in agreement.
      const sessionId = cachedBoard.session?.id;
      if (sessionId != null) {
        void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftFeasibility(sessionId) });
        // Fit, the autopick preview and the journal are server derivations of
        // the board, so any board event can move them.
        void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftTeamFits(sessionId) });
        void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftTeamQueues(sessionId) });
        void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftJournal(sessionId) });
      }
      const affectedPickId = event.data.pick_id ?? cachedBoard.current_pick?.id;
      if (affectedPickId != null) {
        void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftPickOptions(affectedPickId) });
      }
    },
    [queryClient, queryKey, topic]
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
        queryKey,
        event: pendingEvent,
      });
    }
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

  const extendClock = useMutation({
    mutationFn: (v: { pickId: number; version: number; seconds: number }) =>
      draftService.extend(v.pickId, { expected_version: v.version, seconds: v.seconds }),
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

  return { makePick, autopick, override, lifecycle, editPlayerRole, extendClock };
}

/**
 * The mutation set the draft room passes around. Named here, at the module that
 * owns it, so the room's components import one name instead of each spelling
 * out `ReturnType<typeof useDraftMutations>`.
 */
export type DraftMutations = ReturnType<typeof useDraftMutations>;
