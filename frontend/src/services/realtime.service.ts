"use client";

import { useRealtimeStore } from "@/stores/realtime.store";
import type {
  ClientRealtimeFrame,
  EventFrame,
  RealtimeEventEnvelope,
  ServerRealtimeFrame
} from "@/types/realtime.types";

type RealtimeHandler<TData = Record<string, unknown>> = (
  event: RealtimeEventEnvelope<TData>
) => void;

type TopicHandlers = Map<number, RealtimeHandler>;

const HEARTBEAT_INTERVAL_MS = 25_000;
const PONG_TIMEOUT_MS = 10_000;
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

export function buildRealtimeWebSocketUrl(
  realtimeBase: string | undefined = undefined,
  origin = typeof window !== "undefined" ? window.location.origin : "http://localhost"
): string {
  if (realtimeBase) {
    const url = new URL(realtimeBase, origin);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    const pathname = url.pathname.replace(/\/$/, "");
    url.pathname = pathname.endsWith("/ws") ? pathname : `${pathname}/ws`;
    url.search = "";
    return url.toString();
  }

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/api/realtime/ws`;
}

class RealtimeClient {
  private socket: WebSocket | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private heartbeatTimer: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private nextHandlerId = 1;
  private handlersByTopic = new Map<string, TopicHandlers>();

  subscribe<TData>(
    topic: string,
    handler: RealtimeHandler<TData>
  ): () => void {
    if (typeof window === "undefined") {
      return () => undefined;
    }

    let topicHandlers = this.handlersByTopic.get(topic);
    const isNewTopic = !topicHandlers;
    if (!topicHandlers) {
      topicHandlers = new Map();
      this.handlersByTopic.set(topic, topicHandlers);
    }

    const handlerId = this.nextHandlerId++;
    topicHandlers.set(handlerId, handler as RealtimeHandler);

    this.ensureSocket();
    if (isNewTopic && this.socket?.readyState === WebSocket.OPEN) {
      this.sendSubscribe(topic);
    }

    let cleanedUp = false;
    return () => {
      if (cleanedUp) {
        return;
      }
      cleanedUp = true;

      const currentHandlers = this.handlersByTopic.get(topic);
      currentHandlers?.delete(handlerId);
      if (currentHandlers && currentHandlers.size > 0) {
        return;
      }

      this.handlersByTopic.delete(topic);
      this.send({ op: "unsubscribe", topic });

      if (this.handlersByTopic.size === 0) {
        this.closeIdleSocket();
      }
    };
  }

  resubscribe(topic: string): void {
    if (!this.handlersByTopic.has(topic)) {
      return;
    }
    this.sendSubscribe(topic);
  }

  /**
   * Publish an ephemeral frame to a topic (e.g. a live-drag overlay). Fire and
   * forget: silently dropped when the socket is not open, since these frames are
   * transient and losing one is harmless. The server stamps the actor, enforces
   * the topic ACL, and restricts which event types clients may publish.
   */
  publish(topic: string, eventType: string, data: Record<string, unknown>): void {
    if (typeof window === "undefined") {
      return;
    }
    this.send({ op: "publish", topic, event_type: eventType, data });
  }

  private ensureSocket(): void {
    if (this.socket?.readyState === WebSocket.OPEN || this.socket?.readyState === WebSocket.CONNECTING) {
      return;
    }

    this.clearReconnectTimer();
    useRealtimeStore.getState().setConnectionState(this.reconnectAttempt > 0 ? "reconnecting" : "connecting");

    const socket = new WebSocket(buildRealtimeWebSocketUrl());
    this.socket = socket;

    socket.onopen = () => {
      this.reconnectAttempt = 0;
      useRealtimeStore.getState().setConnectionState("connected");
      for (const topic of this.handlersByTopic.keys()) {
        this.sendSubscribe(topic);
      }
      this.startHeartbeat();
    };

    socket.onmessage = (message) => {
      this.handleMessage(message.data);
    };

    socket.onclose = () => {
      this.socket = null;
      this.stopHeartbeat();
      if (this.handlersByTopic.size > 0) {
        this.scheduleReconnect();
      } else {
        useRealtimeStore.getState().setConnectionState("idle");
      }
    };

    socket.onerror = () => {
      socket.close();
    };
  }

  private handleMessage(rawData: unknown): void {
    if (typeof rawData !== "string") {
      return;
    }

    let frame: ServerRealtimeFrame;
    try {
      frame = JSON.parse(rawData) as ServerRealtimeFrame;
    } catch {
      return;
    }

    if (frame.op === "pong") {
      this.clearPongTimer();
      return;
    }

    if (frame.op === "error") {
      console.warn("Realtime subscription error", frame);
      return;
    }

    if (frame.op === "subscribed") {
      useRealtimeStore.getState().setLastEventId(frame.topic, frame.cursor);
      return;
    }

    if (frame.op !== "event") {
      return;
    }

    this.dispatchEvent(frame);
  }

  private dispatchEvent(frame: EventFrame): void {
    useRealtimeStore.getState().setLastEventId(frame.topic, frame.event.event_id);
    const handlers = this.handlersByTopic.get(frame.topic);
    if (!handlers) {
      return;
    }

    for (const handler of Array.from(handlers.values())) {
      handler(frame.event);
    }
  }

  private sendSubscribe(topic: string): void {
    // Request catch-up replay only after a snapshot or prior event seeded a
    // cursor for this topic. A fresh page without a baseline stays live-only, so
    // it does not replay the entire persisted backlog into redundant refetches.
    const afterEventId = useRealtimeStore.getState().lastEventIdByTopic[topic];
    this.send({
      op: "subscribe",
      topic,
      ...(afterEventId !== undefined ? { after_event_id: afterEventId } : {})
    });
  }

  private send(frame: ClientRealtimeFrame): void {
    if (this.socket?.readyState !== WebSocket.OPEN) {
      return;
    }
    this.socket.send(JSON.stringify(frame));
  }

  private scheduleReconnect(): void {
    this.clearReconnectTimer();
    useRealtimeStore.getState().setConnectionState("reconnecting");
    const delay = Math.min(
      RECONNECT_BASE_MS * 2 ** this.reconnectAttempt,
      RECONNECT_MAX_MS
    );
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => this.ensureSocket(), delay);
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeatTimer = setInterval(() => {
      this.send({ op: "ping" });
      this.clearPongTimer();
      this.pongTimer = setTimeout(() => {
        this.socket?.close();
      }, PONG_TIMEOUT_MS);
    }, HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer);
      this.heartbeatTimer = null;
    }
    this.clearPongTimer();
  }

  private clearPongTimer(): void {
    if (this.pongTimer) {
      clearTimeout(this.pongTimer);
      this.pongTimer = null;
    }
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  private closeIdleSocket(): void {
    this.clearReconnectTimer();
    this.stopHeartbeat();
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    useRealtimeStore.getState().setConnectionState("idle");
  }
}

export const realtimeClient = new RealtimeClient();
