"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import { realtimeClient } from "@/services/realtime.service";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";
import type { BalancerRosterKey } from "@/types/balancer-admin.types";

/** Mirrors `BALANCER_DRAG` in shared/services/balancer_realtime.py. */
export const BALANCER_DRAG_EVENT = "balancer.drag";

/** A ghost expires if no frame arrives within this window (covers missed `end` / disconnect). */
const GHOST_TTL_MS = 2000;
/** Min interval between outgoing `over` frames while dragging. */
const OVER_THROTTLE_MS = 40;

export type DragPhase = "start" | "over" | "end";

/** Identity of the dragged player + its origin, set on drag start. */
export type DragStartPayload = {
  playerId: string;
  playerName: string;
  fromTeamIndex: number;
  fromRoleKey: BalancerRosterKey;
};

/** The slot the dragged card currently hovers (semantic, not pixel coords). */
export type DragOverPayload = {
  overTeamIndex: number | null;
  overRoleKey: BalancerRosterKey | null;
  overInsertIndex: number | null;
};

/** A remote user's in-progress drag, resolved for rendering a ghost. */
export type RemoteDrag = DragStartPayload &
  DragOverPayload & {
    userId: number;
    updatedAt: number;
  };

/** Max length of a remote-supplied player name we keep (defensive bound on untrusted text). */
const MAX_PLAYER_NAME_LENGTH = 80;

/** Wire shape of a `balancer.drag` event payload (snake_case to match the backend). */
export type DragEventData = {
  phase: DragPhase;
  player_id?: string;
  player_name?: string;
  from_team_index?: number;
  from_role_key?: BalancerRosterKey;
  over_team_index?: number | null;
  over_role_key?: BalancerRosterKey | null;
  over_insert_index?: number | null;
};

type RemoteDragMap = Record<number, RemoteDrag>;

/**
 * Fold an incoming drag event into the ghost map. `start`/`over` frames carry the
 * full player identity (so a late-joining `over` needs no prior `start`); `end`
 * removes the ghost. Frames from `currentUserId` and frames without an actor are
 * ignored (the local user renders their own drag directly).
 */
export function applyDragEvent(
  drags: RemoteDragMap,
  actorUserId: number | null,
  data: DragEventData,
  currentUserId: number | null,
  nowMs: number,
): RemoteDragMap {
  if (actorUserId == null || actorUserId === currentUserId) {
    return drags;
  }

  if (data.phase === "end") {
    if (!(actorUserId in drags)) {
      return drags;
    }
    const next = { ...drags };
    delete next[actorUserId];
    return next;
  }

  return {
    ...drags,
    [actorUserId]: {
      userId: actorUserId,
      playerId: data.player_id ?? "",
      playerName: (data.player_name ?? "").slice(0, MAX_PLAYER_NAME_LENGTH),
      fromTeamIndex: data.from_team_index ?? 0,
      fromRoleKey: data.from_role_key ?? "Tank",
      overTeamIndex: data.over_team_index ?? null,
      overRoleKey: data.over_role_key ?? null,
      overInsertIndex: data.over_insert_index ?? null,
      updatedAt: nowMs,
    },
  };
}

/** Drop ghosts that have not been refreshed within the TTL. */
export function pruneStaleDrags(drags: RemoteDragMap, nowMs: number, ttlMs = GHOST_TTL_MS): RemoteDragMap {
  const entries = Object.values(drags).filter((drag) => nowMs - drag.updatedAt <= ttlMs);
  if (entries.length === Object.keys(drags).length) {
    return drags;
  }
  return Object.fromEntries(entries.map((drag) => [drag.userId, drag]));
}

type UseBalancerDragGhostsResult = {
  remoteDrags: RemoteDrag[];
  broadcastDragStart: (payload: DragStartPayload) => void;
  broadcastDragOver: (over: DragOverPayload) => void;
  broadcastDragEnd: () => void;
};

/**
 * Live-drag overlay: subscribes to `balancer.drag` on the tournament topic to
 * collect other users' in-progress drags (as ghosts) and exposes throttled
 * publishers to broadcast the local user's drag. Purely a visibility layer —
 * it never mutates roster state.
 */
export function useBalancerDragGhosts({
  topic,
  currentUserId,
}: {
  topic: string | null;
  currentUserId: number | null;
}): UseBalancerDragGhostsResult {
  const [drags, setDrags] = useState<RemoteDragMap>({});
  const [trackedTopic, setTrackedTopic] = useState(topic);
  const startPayloadRef = useRef<DragStartPayload | null>(null);
  const lastOverSentRef = useRef(0);

  // Reset ghosts when the topic changes, using the render-phase "adjust state on
  // prop change" pattern (cheaper and lint-clean vs. a setState-in-effect reset).
  if (topic !== trackedTopic) {
    setTrackedTopic(topic);
    setDrags({});
  }

  const handleEvent = useCallback(
    (event: RealtimeEventEnvelope<DragEventData>) => {
      if (event.event_type !== BALANCER_DRAG_EVENT) {
        return;
      }
      setDrags((prev) => applyDragEvent(prev, event.actor_user_id, event.data, currentUserId, Date.now()));
    },
    [currentUserId],
  );

  useRealtimeTopic(topic, handleEvent);

  // Periodically prune ghosts whose owner stopped sending frames (missed `end`
  // or disconnect). Ref resets here cover the topic switch handled above.
  useEffect(() => {
    startPayloadRef.current = null;
    lastOverSentRef.current = 0;
    if (!topic) {
      return;
    }
    const interval = setInterval(() => {
      setDrags((prev) => pruneStaleDrags(prev, Date.now()));
    }, 500);
    return () => clearInterval(interval);
  }, [topic]);

  const broadcastDragStart = useCallback(
    (payload: DragStartPayload) => {
      startPayloadRef.current = payload;
      lastOverSentRef.current = 0;
      if (!topic) {
        return;
      }
      realtimeClient.publish(topic, BALANCER_DRAG_EVENT, serializeDrag("start", payload, null));
    },
    [topic],
  );

  const broadcastDragOver = useCallback(
    (over: DragOverPayload) => {
      const start = startPayloadRef.current;
      if (!topic || !start) {
        return;
      }
      const now = Date.now();
      if (now - lastOverSentRef.current < OVER_THROTTLE_MS) {
        return;
      }
      lastOverSentRef.current = now;
      realtimeClient.publish(topic, BALANCER_DRAG_EVENT, serializeDrag("over", start, over));
    },
    [topic],
  );

  const broadcastDragEnd = useCallback(() => {
    startPayloadRef.current = null;
    if (!topic) {
      return;
    }
    realtimeClient.publish(topic, BALANCER_DRAG_EVENT, { phase: "end" });
  }, [topic]);

  return {
    remoteDrags: Object.values(drags),
    broadcastDragStart,
    broadcastDragOver,
    broadcastDragEnd,
  };
}

function serializeDrag(
  phase: DragPhase,
  start: DragStartPayload,
  over: DragOverPayload | null,
): Record<string, unknown> {
  return {
    phase,
    player_id: start.playerId,
    player_name: start.playerName,
    from_team_index: start.fromTeamIndex,
    from_role_key: start.fromRoleKey,
    over_team_index: over?.overTeamIndex ?? null,
    over_role_key: over?.overRoleKey ?? null,
    over_insert_index: over?.overInsertIndex ?? null,
  };
}
