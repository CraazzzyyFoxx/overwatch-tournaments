import { afterEach, beforeEach, describe, expect, it } from "bun:test";

import { realtimeClient } from "@/services/realtime.service";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { ServerRealtimeFrame } from "@/types/realtime.types";

class MockWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 3;

  static instances: MockWebSocket[] = [];

  readyState = MockWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((message: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(readonly url: string) {
    MockWebSocket.instances.push(this);
  }

  open(): void {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
  }

  receive(frame: ServerRealtimeFrame): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }

  send(frame: string): void {
    this.sent.push(frame);
  }

  close(): void {
    if (this.readyState === MockWebSocket.CLOSED) return;
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.();
  }
}

const originalWindow = globalThis.window;
const originalWebSocket = globalThis.WebSocket;
let cleanups: Array<() => void> = [];

function trackCleanup(cleanup: () => void): () => void {
  cleanups.push(cleanup);
  return cleanup;
}

function currentSocket(): MockWebSocket {
  const socket = MockWebSocket.instances.at(-1);
  if (!socket) throw new Error("Expected a realtime socket");
  return socket;
}

describe("realtime subscribed confirmations", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    cleanups = [];
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: { location: { origin: "https://example.test", protocol: "https:", host: "example.test" } },
    });
    globalThis.WebSocket = MockWebSocket as unknown as typeof WebSocket;
    useRealtimeStore.setState({
      connectionState: "idle",
      lastEventIdByTopic: {},
      topicErrors: {},
    });
  });

  afterEach(() => {
    for (const cleanup of cleanups.reverse()) cleanup();
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
    globalThis.WebSocket = originalWebSocket;
  });

  it("notifies every current subscriber after storing the confirmed cursor", () => {
    const topic = "tournament:42:bracket";
    const observedCursors: number[] = [];
    const unsubscribeWithoutCallback = trackCleanup(realtimeClient.subscribe(topic, () => undefined));
    const unsubscribeFirst = trackCleanup(realtimeClient.subscribe(topic, () => undefined, () => {
      observedCursors.push(useRealtimeStore.getState().lastEventIdByTopic[topic]);
    }));
    const unsubscribeSecond = trackCleanup(realtimeClient.subscribe(topic, () => undefined, () => {
      observedCursors.push(useRealtimeStore.getState().lastEventIdByTopic[topic]);
    }));
    const socket = currentSocket();
    socket.open();

    socket.receive({ op: "subscribed", topic, cursor: 23 });

    expect(observedCursors).toEqual([23, 23]);

    unsubscribeFirst();
    socket.receive({ op: "subscribed", topic, cursor: 29 });
    expect(observedCursors).toEqual([23, 23, 29]);

    unsubscribeSecond();
    unsubscribeWithoutCallback();
  });

  it("notifies again after a reconnect confirmation", async () => {
    const topic = "tournament:42:bracket";
    let confirmations = 0;
    const unsubscribe = trackCleanup(realtimeClient.subscribe(topic, () => undefined, () => {
      confirmations += 1;
    }));
    const firstSocket = currentSocket();
    firstSocket.open();
    firstSocket.receive({ op: "subscribed", topic, cursor: 1 });

    firstSocket.close();
    await Bun.sleep(1_050);
    const secondSocket = currentSocket();
    secondSocket.open();
    secondSocket.receive({ op: "subscribed", topic, cursor: 2 });

    expect(confirmations).toBe(2);
    unsubscribe();
  });

  it("does not treat an ordinary event as a subscription confirmation", () => {
    const topic = "tournament:42:bracket";
    let confirmations = 0;
    let events = 0;
    const unsubscribe = trackCleanup(realtimeClient.subscribe(topic, () => {
      events += 1;
    }, () => {
      confirmations += 1;
    }));
    const socket = currentSocket();
    socket.open();

    socket.receive({
      op: "event",
      topic,
      event: {
        event_id: 7,
        event_type: "tournament.updated",
        schema_version: 1,
        occurred_at: "2026-07-15T00:00:00Z",
        actor_user_id: null,
        data: { tournament_id: 42, reason: "results_changed" },
      },
    });

    expect(events).toBe(1);
    expect(confirmations).toBe(0);
    unsubscribe();
  });

  it("reports a failed confirmation callback and continues notifying subscribers", () => {
    const topic = "tournament:42:bracket";
    const reported: unknown[][] = [];
    const originalError = console.error;
    console.error = (...args: unknown[]) => reported.push(args);
    let confirmations = 0;

    try {
      trackCleanup(realtimeClient.subscribe(topic, () => undefined, () => {
        throw new Error("confirmation failed");
      }));
      trackCleanup(realtimeClient.subscribe(topic, () => undefined, () => {
        confirmations += 1;
      }));
      const socket = currentSocket();
      socket.open();

      socket.receive({ op: "subscribed", topic, cursor: 31 });
      socket.receive({ op: "subscribed", topic, cursor: 32 });

      expect(confirmations).toBe(2);
      expect(reported).toHaveLength(2);
      expect(useRealtimeStore.getState().lastEventIdByTopic[topic]).toBe(32);
    } finally {
      console.error = originalError;
    }
  });

  it("reports a failed event handler and continues dispatching events", () => {
    const topic = "tournament:42:bracket";
    const reported: unknown[][] = [];
    const originalError = console.error;
    console.error = (...args: unknown[]) => reported.push(args);
    let events = 0;

    try {
      trackCleanup(realtimeClient.subscribe(topic, () => {
        throw new Error("event failed");
      }));
      trackCleanup(realtimeClient.subscribe(topic, () => {
        events += 1;
      }));
      const socket = currentSocket();
      socket.open();

      for (const eventId of [41, 42]) {
        socket.receive({
          op: "event",
          topic,
          event: {
            event_id: eventId,
            event_type: "tournament.updated",
            schema_version: 1,
            occurred_at: "2026-07-15T00:00:00Z",
            actor_user_id: null,
            data: { tournament_id: 42, reason: "results_changed" },
          },
        });
      }

      expect(events).toBe(2);
      expect(reported).toHaveLength(2);
      expect(useRealtimeStore.getState().lastEventIdByTopic[topic]).toBe(42);
    } finally {
      console.error = originalError;
    }
  });

  it("reset() drops the live socket and reconnects, re-subscribing open topics", () => {
    const topic = "tournament:42:bracket";
    trackCleanup(realtimeClient.subscribe(topic, () => undefined));
    const first = currentSocket();
    first.open();
    expect(first.readyState).toBe(MockWebSocket.OPEN);

    realtimeClient.reset();
    expect(first.readyState).toBe(MockWebSocket.CLOSED);

    const second = currentSocket();
    expect(second).not.toBe(first);
    second.open();
    expect(
      second.sent.some((f) => f.includes('"op":"subscribe"') && f.includes(topic)),
    ).toBe(true);
  });

  it("reset() with no live subscriptions is a safe no-op and stays idle", () => {
    const topic = "tournament:7:bracket";
    const unsubscribe = realtimeClient.subscribe(topic, () => undefined);
    currentSocket().open();
    unsubscribe();

    realtimeClient.reset();
    expect(useRealtimeStore.getState().connectionState).toBe("idle");
  });
});
