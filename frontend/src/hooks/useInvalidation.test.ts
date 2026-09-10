// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useInvalidation, type UseInvalidationOptions } from "@/hooks/useInvalidation";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/**
 * What the single invalidation consumer does with an event, not how it gets
 * one: `useRealtimeTopic` is mocked so a test can fire what the realtime client
 * would (same shape as useRealtimeCoalescedRefetch.test.ts), while the real
 * coalescer and the real resource table run underneath.
 */
type TopicSubscription = {
  onEvent: (event: RealtimeEventEnvelope) => void;
  onSubscribed?: () => void;
};
const subscriptions = new Map<string, TopicSubscription>();

vi.mock("@/hooks/useRealtimeTopic", () => ({
  useRealtimeTopic: (
    topic: string | null | undefined,
    onEvent: (event: RealtimeEventEnvelope) => void,
    _deps: unknown[],
    onSubscribed?: () => void,
  ) => {
    if (!topic) return;
    subscriptions.set(topic, { onEvent, onSubscribed });
  },
}));

/** Past MIN_DELAY_MS + the whole JITTER_MS window, so a flush is due. */
const FLUSH_MS = 3_000;

let eventIdCounter = 0;
function fireEvent(topic: string, resources: unknown): void {
  const subscription = subscriptions.get(topic);
  if (!subscription) throw new Error(`no subscription registered for topic "${topic}"`);
  act(() => {
    subscription.onEvent({
      event_id: ++eventIdCounter,
      event_type: "invalidation",
      schema_version: 1,
      occurred_at: "2026-09-09T00:00:00Z",
      actor_user_id: null,
      data: { resources },
    });
  });
}

let container: HTMLDivElement;
let root: Root | undefined;
let queryClient: QueryClient;
/** Every key handed to `invalidateQueries`, serialized, in call order. */
let invalidatedKeys: string[];

function Harness(props: UseInvalidationOptions) {
  useInvalidation(props);
  return null;
}

function render(props: UseInvalidationOptions): void {
  act(() => {
    root?.render(
      createElement(QueryClientProvider, { client: queryClient }, createElement(Harness, props)),
    );
  });
}

beforeEach(() => {
  vi.useFakeTimers();
  subscriptions.clear();
  eventIdCounter = 0;
  invalidatedKeys = [];
  useRealtimeStore.setState({ connectionState: "idle" });
  queryClient = new QueryClient();
  vi.spyOn(queryClient, "invalidateQueries").mockImplementation((filters) => {
    invalidatedKeys.push(JSON.stringify(filters?.queryKey));
    return Promise.resolve();
  });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) act(() => root?.unmount());
  root = undefined;
  container.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("useInvalidation", () => {
  it("drops the union of two resources' keys, each exactly once", () => {
    render({ scopeKind: "tournament", scopeId: 42, workspaceId: 7 });

    // Two events naming overlapping resource sets: the flush is one, and a key
    // both resources stale is dropped once, not twice.
    fireEvent("tournament:42:invalidation", ["tournament.teams"]);
    fireEvent("tournament:42:invalidation", ["tournament.teams", "tournament.standings"]);
    act(() => vi.advanceTimersByTime(FLUSH_MS));

    // tournament.teams
    expect(invalidatedKeys).toContain(JSON.stringify(["teams", 42]));
    expect(invalidatedKeys).toContain(JSON.stringify(["balancer-public", "balance", 42]));
    // tournament.standings
    expect(invalidatedKeys).toContain(JSON.stringify(["standings", 42]));
    expect(invalidatedKeys).toContain(JSON.stringify(["hero-playtime", "tournament", 42]));
    expect(new Set(invalidatedKeys).size).toBe(invalidatedKeys.length);
  });

  it("ignores an unknown resource without dropping the known ones with it", () => {
    render({ scopeKind: "tournament", scopeId: 42 });

    fireEvent("tournament:42:invalidation", ["tournament.from_the_future", "tournament.stages"]);
    act(() => vi.advanceTimersByTime(FLUSH_MS));

    expect(invalidatedKeys).toEqual([JSON.stringify(["admin", "stages", 42])]);
  });

  it("stays silent for an event naming no resource this client knows", () => {
    render({ scopeKind: "tournament", scopeId: 42 });

    fireEvent("tournament:42:invalidation", ["tournament.from_the_future"]);
    fireEvent("tournament:42:invalidation", []);
    fireEvent("tournament:42:invalidation", undefined);
    act(() => vi.advanceTimersByTime(FLUSH_MS));

    expect(invalidatedKeys).toEqual([]);
  });

  it("re-runs the route only for a resource a refetch cannot fix", () => {
    const onRouteRefresh = vi.fn();
    render({ scopeKind: "tournament", scopeId: 42, onRouteRefresh });

    fireEvent("tournament:42:invalidation", ["tournament.standings"]);
    act(() => vi.advanceTimersByTime(FLUSH_MS));
    expect(onRouteRefresh).not.toHaveBeenCalled();

    fireEvent("tournament:42:invalidation", ["tournament.structure"]);
    act(() => vi.advanceTimersByTime(FLUSH_MS));
    expect(onRouteRefresh).toHaveBeenCalledTimes(1);
  });

  it("does not carry a pending resource across a scope change", () => {
    render({ scopeKind: "tournament", scopeId: 42 });
    // Accumulated but never flushed: it belongs to tournament 42.
    fireEvent("tournament:42:invalidation", ["tournament.teams"]);

    render({ scopeKind: "tournament", scopeId: 99 });
    fireEvent("tournament:99:invalidation", ["tournament.stages"]);
    act(() => vi.advanceTimersByTime(FLUSH_MS));

    expect(invalidatedKeys).toEqual([JSON.stringify(["admin", "stages", 99])]);
  });
});
