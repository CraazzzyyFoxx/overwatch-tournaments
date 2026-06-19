"use client";

import { useCallback, useEffect, useState } from "react";

import { useRealtimeTopic } from "@/hooks/useRealtimeTopic";
import adminService from "@/services/admin.service";
import type { LogProcessingRecord, QueueDepth } from "@/types/admin.types";

export type LogStreamState = {
  connected: boolean;
  error: string | null;
  queues: QueueDepth[];
  recentLogs: LogProcessingRecord[];
  lastUpdated: Date | null;
};

const INITIAL_STATE: LogStreamState = {
  connected: false,
  error: null,
  queues: [],
  recentLogs: [],
  lastUpdated: null,
};

// Queue depths have no realtime push signal (they're a RabbitMQ management
// snapshot), so they're refreshed on a light interval; recent-log changes arrive
// in real time over the workspace WS topic.
const QUEUE_POLL_MS = 5000;
const RECENT_LOG_LIMIT = 20;

/**
 * Live queue depths + recent log-processing records for the admin monitor.
 *
 * Replaces the former SSE endpoint: recent logs refresh in real time via the
 * `workspace:{id}:logs` realtime topic (parser emits a thin `logs.updated`
 * signal on each processing completion), and queue depths refresh on a short
 * interval. Both are read through the gateway-served RPC endpoints
 * (`admin/logs/history`, `admin/logs/queue-status`).
 */
export function useLogStream(enabled = true, workspaceId: number | null = null): LogStreamState {
  const [state, setState] = useState<LogStreamState>(INITIAL_STATE);

  const refetch = useCallback(async () => {
    try {
      const [queues, history] = await Promise.all([
        adminService.getQueueStatus(),
        adminService.getLogHistory(undefined, { workspaceId, limit: RECENT_LOG_LIMIT }),
      ]);
      setState({
        connected: true,
        error: null,
        queues,
        recentLogs: history.items,
        lastUpdated: new Date(),
      });
    } catch (err) {
      setState((s) => ({
        ...s,
        connected: false,
        error: err instanceof Error ? err.message : "Failed to load log status",
      }));
    }
  }, [workspaceId]);

  // Initial fetch + queue-depth polling.
  useEffect(() => {
    if (!enabled) {
      setState(INITIAL_STATE);
      return;
    }
    let cancelled = false;
    const tick = () => {
      if (!cancelled) void refetch();
    };
    tick();
    const id = setInterval(tick, QUEUE_POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [enabled, refetch]);

  // Real-time: refetch immediately when parser signals a log state change.
  const topic = enabled && workspaceId != null ? `workspace:${workspaceId}:logs` : null;
  useRealtimeTopic(topic, () => void refetch(), [refetch]);

  return state;
}
