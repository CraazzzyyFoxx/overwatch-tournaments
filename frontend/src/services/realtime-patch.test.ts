import { describe, expect, it } from "bun:test";
import { QueryClient } from "@tanstack/react-query";

import { applyResourcePatch, registerRealtimeResource } from "@/services/realtime-patch";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

type Counter = { value: number };

function incEvent(by: number): RealtimeEventEnvelope {
  return {
    event_id: 1,
    event_type: "counter.inc",
    schema_version: 1,
    occurred_at: "2026-07-18T00:00:00Z",
    actor_user_id: null,
    data: { by },
  };
}

const counterKey = (id: number) => ["counter", id] as const;

registerRealtimeResource<Counter>("test.counter", {
  queryKey: counterKey,
  reduce: (snapshot, event) => ({
    value: snapshot.value + Number(event.data.by ?? 1),
  }),
});

describe("applyResourcePatch", () => {
  it("folds the event into the cached snapshot in place", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(counterKey(7), { value: 10 });

    const outcome = applyResourcePatch(queryClient, {
      resource: "test.counter",
      resourceId: 7,
      event: incEvent(5),
    });

    expect(outcome).toBe("applied");
    expect(queryClient.getQueryData(counterKey(7))).toEqual({ value: 15 });
  });

  it("reports uncached (so the caller refetches) when no snapshot exists yet", () => {
    const queryClient = new QueryClient();

    const outcome = applyResourcePatch(queryClient, {
      resource: "test.counter",
      resourceId: 9,
      event: incEvent(1),
    });

    expect(outcome).toBe("uncached");
  });

  it("reports unregistered for an unknown resource without throwing", () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(["other"], { value: 1 });

    const outcome = applyResourcePatch(queryClient, {
      resource: "nope.unknown",
      resourceId: 1,
      event: incEvent(1),
    });

    expect(outcome).toBe("unregistered");
    expect(queryClient.getQueryData(["other"])).toEqual({ value: 1 });
  });
});
