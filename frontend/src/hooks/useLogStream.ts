"use client";

import { useEffect, useRef, useState } from "react";
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

/**
 * Connects to the SSE log stream endpoint and returns live queue depths
 * and recent log processing records.
 *
 * The token is read from the `aqt_access_token` cookie so the EventSource
 * can authenticate (EventSource does not support custom headers).
 */
export function useLogStream(enabled = true, workspaceId: number | null = null): LogStreamState {
  const [state, setState] = useState<LogStreamState>(INITIAL_STATE);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled) return;

    let cancelled = false;

    async function connect() {
      // Get access token from cookie (client-side only)
      let token: string | undefined;
      try {
        const Cookies = (await import("js-cookie")).default;
        token = Cookies.get("aqt_access_token");
      } catch {
        // js-cookie not available
      }

      if (cancelled) return;

      if (!token) {
        setState((s) => ({ ...s, error: "Not authenticated", connected: false }));
        return;
      }

      let url = `/api/parser/admin/logs/stream?token=${encodeURIComponent(token)}`;
      if (workspaceId !== null) {
        url += `&workspace_id=${workspaceId}`;
      }
      const es = new EventSource(url);
      esRef.current = es;

      es.onopen = () => {
        if (!cancelled) {
          setState((s) => ({ ...s, connected: true, error: null }));
        }
      };

      es.addEventListener("update", (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse(event.data);
          setState({
            connected: true,
            error: null,
            queues: data.queues ?? [],
            recentLogs: data.recent_logs ?? [],
            lastUpdated: new Date(),
          });
        } catch {
          // ignore malformed event
        }
      });

      es.addEventListener("error", (event) => {
        if (cancelled) return;
        try {
          const data = JSON.parse((event as MessageEvent).data ?? "{}");
          setState((s) => ({ ...s, error: data.error ?? "Stream error" }));
        } catch {
          // ignore
        }
      });

      es.onerror = () => {
        if (!cancelled) {
          setState((s) => ({ ...s, connected: false, error: "Connection lost, reconnecting…" }));
        }
      };
    }

    void connect();

    return () => {
      cancelled = true;
      esRef.current?.close();
      esRef.current = null;
      setState(INITIAL_STATE);
    };
  }, [enabled, workspaceId]);

  return state;
}
