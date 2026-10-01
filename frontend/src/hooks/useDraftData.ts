"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { hashKey, queryOptions, useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { tournamentQueryKeys } from "@/lib/tournament/query-keys";
import draftService from "@/services/draft.service";
import userService from "@/services/user.service";
import { realtimeClient } from "@/services/realtime.service";
import { useRealtimeStore } from "@/stores/realtime.store";
import { applyResourcePatch, registerRealtimeResource } from "@/services/realtime-patch";
import { type Coalescer, createTrailingCoalescer } from "@/lib/realtime/coalesce";
import type {
  DraftBoard,
  DraftEventData,
  DraftPresenceState,
  DraftRole,
  DraftRoleEditRequest,
  DraftTeamQueueResponse
} from "@/types/draft.types";
import type { RealtimeConnectionState, RealtimeEventEnvelope } from "@/types/realtime.types";

import {
  applyDraftEvent,
  draftDerivedScope,
  draftEventNeedsSnapshot,
  presenceFromEvent,
  type DraftDerivedScope
} from "@/lib/draft/logic";

const MAX_PENDING_DRAFT_EVENTS = 100;
const EMPTY_DRAFT_PRESENCE: DraftPresenceState = { users: {}, anonymous_viewer_count: 0 };

/**
 * Fit, queue and feasibility: server derivations of the board that
 * `useDraftRealtime` re-reads on exactly the events that move them. Never stale
 * by age -- a focus or remount refetch would re-ask what no event changed -- and
 * never retried: the next event re-asks anyway, and retried 504s are what held
 * the balancer at its timeout during the 2026-09-30 draft.
 */
const REALTIME_DERIVED = { staleTime: Infinity, retry: false } as const;

/**
 * One re-read of the derived reads per burst: a pick publishes `pick_made` and
 * `pick_started` in one transaction, milliseconds apart. Short and unjittered:
 * the captain on the clock waits on it for the autopick preview, and requests
 * that arrive together are what the server's single-flight folds into one run.
 */
const DERIVED_FLUSH_MS = 250;
const ALL_DERIVED: DraftDerivedScope = { teams: "all", feasibility: true };

/**
 * The board poll is a safety net that every viewer runs, anonymous spectators
 * included. While the socket is up it only repairs a pub/sub frame lost without
 * a disconnect, so it is slow; while the socket is down it is the only feed.
 */
const BOARD_POLL_CONNECTED_MS = 120_000;
const BOARD_POLL_DISCONNECTED_MS = 30_000;

function derivedQueryKeys(sessionId: number, scope: DraftDerivedScope | null): QueryKey[] {
  // The journal logs clock changes too; it is only read while an organizer has it open.
  const keys: QueryKey[] = [tournamentQueryKeys.draftJournal(sessionId)];
  if (scope == null) return keys;
  if (scope.teams === "all") {
    keys.push(tournamentQueryKeys.draftTeamFits(sessionId), tournamentQueryKeys.draftTeamQueues(sessionId));
  } else {
    keys.push(
      tournamentQueryKeys.draftTeamFit(sessionId, scope.teams),
      tournamentQueryKeys.draftTeamQueue(sessionId, scope.teams)
    );
  }
  if (scope.feasibility) keys.push(tournamentQueryKeys.draftFeasibility(sessionId));
  return keys;
}

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
  const connected = useRealtimeStore((s) => s.connectionState === "connected");
  const pollMs = connected ? BOARD_POLL_CONNECTED_MS : BOARD_POLL_DISCONNECTED_MS;
  return useQuery({
    queryKey: tournamentQueryKeys.draftBoard(tournamentId),
    queryFn: () => draftService.getTournamentBoard(tournamentId),
    enabled: Number.isFinite(tournamentId) && tournamentId > 0,
    refetchInterval: (query) => (query.state.data?.session.status === "live" ? pollMs : false),
  });
}

export function useDraftFeasibilityQuery(sessionId: number | null, enabled = true) {
  return useQuery({
    queryKey: tournamentQueryKeys.draftFeasibility(sessionId ?? 0),
    queryFn: () => draftService.getFeasibility(sessionId!),
    enabled: enabled && sessionId != null && sessionId > 0,
    ...REALTIME_DERIVED
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
    enabled: enabled && sessionId != null && teamId != null,
    ...REALTIME_DERIVED,
    // Without retries one 504 would toast every captain at once; a missing fit
    // column already says it, and the next event re-reads it.
    meta: { suppressErrorToast: true }
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
    enabled: sessionId != null && teamId != null,
    ...REALTIME_DERIVED
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

const draftPlayerCard = (userId: number) =>
  queryOptions({
    queryKey: tournamentQueryKeys.draftPlayerCard(userId),
    queryFn: () => userService.getDraftCard(userId),
    staleTime: 5 * 60_000
  });

/** Career stats for the player card; keyed by the domain user id, cached across sessions. */
export function useDraftPlayerCardQuery(userId: number | null) {
  return useQuery({ ...draftPlayerCard(userId ?? 0), enabled: userId != null });
}

/**
 * Warms the card of the row the pointer rests on: the card is bottom-anchored,
 * so data that lands after it opens grows it upwards and the header jumps. The
 * delay keeps a pointer sweeping across the list from fetching every row it
 * crosses. `null` cancels the pending warm-up.
 */
export function useDraftPlayerCardPrefetch() {
  const client = useQueryClient();
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  return useCallback(
    (userId: number | null) => {
      window.clearTimeout(timer.current);
      if (userId == null) return;
      timer.current = window.setTimeout(() => void client.prefetchQuery(draftPlayerCard(userId)), 120);
    },
    [client]
  );
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

  // Derived reads collect here and are re-read once per burst (DERIVED_FLUSH_MS).
  const derivedRef = useRef(new Map<string, QueryKey>());
  const derivedFlushRef = useRef<Coalescer | null>(null);
  useEffect(() => {
    const pending = derivedRef.current;
    const coalescer = createTrailingCoalescer(() => {
      const keys = [...pending.values()];
      pending.clear();
      // A read already in flight is left to land, never cancelled and
      // restarted: the server finishes a cancelled read anyway, so a restart is
      // the same work twice. It is queued again instead and re-read once it
      // lands -- one extra request, and only when the burst overtook it.
      // Collected before any invalidation below starts a fetch of its own.
      const cache = queryClient.getQueryCache();
      for (const key of keys) {
        for (const query of cache.findAll({ queryKey: key, fetchStatus: "fetching" })) {
          pending.set(query.queryHash, query.queryKey);
        }
      }
      for (const key of keys) {
        void queryClient.invalidateQueries({
          queryKey: key,
          predicate: (query) => query.state.fetchStatus !== "fetching",
        });
      }
      if (pending.size > 0) derivedFlushRef.current?.schedule();
    }, DERIVED_FLUSH_MS);
    derivedFlushRef.current = coalescer;
    return () => {
      coalescer.cancel();
      pending.clear();
      derivedFlushRef.current = null;
    };
  }, [queryClient, topic]);
  const scheduleDerived = useCallback((keys: readonly QueryKey[]) => {
    for (const key of keys) derivedRef.current.set(hashKey(key), key);
    derivedFlushRef.current?.schedule();
  }, []);

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
      if (draftEventNeedsSnapshot(event)) {
        void queryClient.invalidateQueries({ queryKey });
      }

      // Derived reads the patch cannot fold in, re-read only where the event
      // moves them (`draftDerivedScope`). Handled here instead of through the
      // invalidation vocabulary: no other consumer has an opinion about them,
      // so there is nothing for a shared resource name to keep in agreement.
      const sessionId = cachedBoard.session?.id;
      if (sessionId != null) {
        scheduleDerived(derivedQueryKeys(sessionId, draftDerivedScope(cachedBoard, event)));
      }
      // Pick options are keyed by pick id, and a role edit or a clock change
      // bumps the pick's version without advancing it. Read only by the captain
      // on the clock, whose confirm waits on it, so it skips the batch.
      const affectedPickId = event.data.pick_id ?? cachedBoard.current_pick?.id;
      if (affectedPickId != null) {
        void queryClient.invalidateQueries({ queryKey: tournamentQueryKeys.draftPickOptions(affectedPickId) });
      }
    },
    [queryClient, queryKey, topic, scheduleDerived]
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

  // On reconnect, the client replays from the cursor; refetch the snapshot and
  // every derived read as a safety net so the room converges even after a long
  // disconnect -- the derived reads never go stale on their own.
  const connectionState = useRealtimeStore((s) => s.connectionState);
  const prev = useRef(connectionState);
  useEffect(() => {
    if (prev.current === "reconnecting" && connectionState === "connected") {
      queryClient.invalidateQueries({ queryKey });
      const sessionId = queryClient.getQueryData<DraftBoard | null>(queryKey)?.session.id;
      if (sessionId != null) scheduleDerived(derivedQueryKeys(sessionId, ALL_DERIVED));
    }
    prev.current = connectionState;
  }, [connectionState, queryClient, queryKey, scheduleDerived]);

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
