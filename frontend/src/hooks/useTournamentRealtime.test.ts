// @vitest-environment happy-dom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTournamentRealtime } from "@/hooks/useTournamentRealtime";
import type * as TournamentRealtimeHelpersModule from "@/hooks/tournamentRealtime.helpers";
import type { TournamentChangedReason } from "@/hooks/tournamentRealtime.helpers";
import { useRealtimeStore } from "@/stores/realtime.store";
import type { RealtimeEventEnvelope } from "@/types/realtime.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

/**
 * This file tests bracket's own onEvent/onFlush/onCatchUp wiring on top of
 * useRealtimeCoalescedRefetch (already covered standalone by that hook's own
 * test file) -- the severity-ranked reason merge, the disjoint
 * registration_changed side-signal, and the catch-up-plan-vs-update-plan
 * split are proven here by spying on the two plan-applying functions rather
 * than re-deriving their invalidation footprints (already covered by
 * tournamentRealtime.helpers.test.ts).
 */
const applyTournamentRealtimeUpdate = vi.fn();
const applyTournamentRealtimeCatchUp = vi.fn();

vi.mock("@/hooks/tournamentRealtime.helpers", async (importOriginal) => {
  const actual = await importOriginal<typeof TournamentRealtimeHelpersModule>();
  return {
    ...actual,
    applyTournamentRealtimeUpdate: (...args: unknown[]) => applyTournamentRealtimeUpdate(...args),
    applyTournamentRealtimeCatchUp: (...args: unknown[]) =>
      applyTournamentRealtimeCatchUp(...args),
  };
});

/** Mirrors useRealtimeCoalescedRefetch.test.ts's mock -- captures what the
 * real useRealtimeTopic wires up per topic so a test can fire what the
 * realtime client would, without a real websocket. */
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

let eventIdCounter = 0;
function fireEvent(
  topic: string,
  data: { tournament_id?: number; reason?: TournamentChangedReason } = {},
): void {
  const subscription = subscriptions.get(topic);
  if (!subscription) throw new Error(`no subscription registered for topic "${topic}"`);
  eventIdCounter += 1;
  act(() => {
    subscription.onEvent({
      event_id: eventIdCounter,
      event_type: "tournament.updated",
      schema_version: 1,
      occurred_at: "2026-08-24T00:00:00Z",
      actor_user_id: null,
      data,
    });
  });
}

function fireSubscribed(topic: string): void {
  const subscription = subscriptions.get(topic);
  act(() => subscription?.onSubscribed?.());
}

const queryClient = new QueryClient();

function Harness(props: Parameters<typeof useTournamentRealtime>[0]) {
  useTournamentRealtime(props);
  return null;
}

let container: HTMLDivElement;
let root: Root | undefined;

function renderHarness(props: Parameters<typeof useTournamentRealtime>[0]): void {
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
  applyTournamentRealtimeUpdate.mockClear();
  applyTournamentRealtimeCatchUp.mockClear();
  useRealtimeStore.setState({ connectionState: "idle" });
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

function mount(props: Parameters<typeof useTournamentRealtime>[0]): void {
  renderHarness(props);
}

describe("useTournamentRealtime", () => {
  it("debounces a normal flush within [250, 2750)ms and applies the update plan for that reason", () => {
    const randomSpy = vi.spyOn(Math, "random").mockReturnValue(0.4);
    mount({ tournamentId: 1 });

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "bracket_changed" });
    expect(applyTournamentRealtimeUpdate).not.toHaveBeenCalled();

    // delay = 250 + floor(0.4 * 2500) = 1250
    act(() => {
      vi.advanceTimersByTime(1249);
    });
    expect(applyTournamentRealtimeUpdate).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledTimes(1);
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledWith(
      expect.anything(),
      1,
      undefined,
      "bracket_changed",
      undefined,
      1,
    );

    randomSpy.mockRestore();
  });

  it("runs the broader catch-up plan (not a normal update) on first subscribe", () => {
    mount({ tournamentId: 1, workspaceId: 7 });

    fireSubscribed("tournament:1:bracket");

    expect(applyTournamentRealtimeCatchUp).toHaveBeenCalledTimes(1);
    expect(applyTournamentRealtimeCatchUp).toHaveBeenCalledWith(expect.anything(), 1, 7, 1);
    expect(applyTournamentRealtimeUpdate).not.toHaveBeenCalled();
  });

  it("runs the catch-up plan again on reconnect once its leading window has elapsed", () => {
    mount({ tournamentId: 1 });

    fireSubscribed("tournament:1:bracket");
    expect(applyTournamentRealtimeCatchUp).toHaveBeenCalledTimes(1);

    // Within the leading window: suppressed.
    fireSubscribed("tournament:1:bracket");
    expect(applyTournamentRealtimeCatchUp).toHaveBeenCalledTimes(1);

    act(() => {
      vi.advanceTimersByTime(100);
    });
    fireSubscribed("tournament:1:bracket");
    expect(applyTournamentRealtimeCatchUp).toHaveBeenCalledTimes(2);
  });

  it("skips the redundant registration_changed refetch when structure_changed already covers it in the same window", () => {
    mount({ tournamentId: 1 });

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "structure_changed" });
    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "registration_changed" });

    act(() => {
      vi.advanceTimersByTime(2750);
    });

    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledTimes(1);
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledWith(
      expect.anything(),
      1,
      undefined,
      "structure_changed",
      undefined,
      1,
    );
  });

  it("applies a form edit alongside a bracket-family reason instead of dropping it", () => {
    mount({ tournamentId: 1, workspaceId: 7 });

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "structure_changed" });
    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "registration_form_changed" });

    act(() => {
      vi.advanceTimersByTime(2750);
    });

    // Unlike registration_changed, the form key is in no other reason's plan,
    // so structure_changed does not supersede it. Before this reason existed
    // onEvent dropped every unrecognized reason outright.
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledTimes(2);
    expect(applyTournamentRealtimeUpdate).toHaveBeenNthCalledWith(
      2,
      expect.anything(),
      1,
      7,
      "registration_form_changed",
      undefined,
      1,
    );
  });

  it("applies both a bracket-family reason and a separate registration_changed refetch when the reason isn't structure_changed", () => {
    mount({ tournamentId: 1 });

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "bracket_changed" });
    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "registration_changed" });

    act(() => {
      vi.advanceTimersByTime(2750);
    });

    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledTimes(2);
    expect(applyTournamentRealtimeUpdate).toHaveBeenNthCalledWith(
      1,
      expect.anything(),
      1,
      undefined,
      "bracket_changed",
      undefined,
      1,
    );
    expect(applyTournamentRealtimeUpdate).toHaveBeenNthCalledWith(
      2,
      expect.anything(),
      1,
      undefined,
      "registration_changed",
      undefined,
      1,
    );
  });

  it("applies registration_changed alone when no bracket-family reason lands in the same window", () => {
    mount({ tournamentId: 1 });

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "registration_changed" });

    act(() => {
      vi.advanceTimersByTime(2750);
    });

    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledTimes(1);
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledWith(
      expect.anything(),
      1,
      undefined,
      "registration_changed",
      undefined,
      1,
    );
  });

  it("keeps the strongest bracket-family reason seen when multiple waves land in the same window", () => {
    mount({ tournamentId: 1 });

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "bracket_changed" });
    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "results_changed" });

    act(() => {
      vi.advanceTimersByTime(2750);
    });

    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledTimes(1);
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledWith(
      expect.anything(),
      1,
      undefined,
      "results_changed",
      undefined,
      1,
    );
  });

  it("calls onUpdate/onStructureChanged from the flush, firing onStructureChanged only for structure_changed", () => {
    const onStructureChanged = vi.fn();
    const onUpdate = vi.fn();
    mount({ tournamentId: 1, onUpdate, onStructureChanged });

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "bracket_changed" });
    act(() => {
      vi.advanceTimersByTime(2750);
    });
    expect(onStructureChanged).not.toHaveBeenCalled();
    expect(onUpdate).toHaveBeenCalledWith("bracket_changed");

    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "structure_changed" });
    act(() => {
      vi.advanceTimersByTime(2750);
    });
    expect(onStructureChanged).toHaveBeenCalledTimes(1);
    expect(onUpdate).toHaveBeenCalledWith("structure_changed");
  });

  it("ignores events for a different tournament_id", () => {
    mount({ tournamentId: 1 });

    fireEvent("tournament:1:bracket", { tournament_id: 2, reason: "bracket_changed" });
    act(() => {
      vi.advanceTimersByTime(2750);
    });
    expect(applyTournamentRealtimeUpdate).not.toHaveBeenCalled();
  });

  it("drops a pending reason instead of leaking it into the next tournament's flush when tournamentId changes without unmounting", () => {
    mount({ tournamentId: 1 });

    // Pending under tournament 1's topic, never flushed before the switch.
    fireEvent("tournament:1:bracket", { tournament_id: 1, reason: "results_changed" });

    // Switch to a different tournament without unmounting (e.g. an admin
    // dropdown re-selecting selectedTournamentId).
    renderHarness({ tournamentId: 2 });
    applyTournamentRealtimeCatchUp.mockClear();

    // Only a registration_changed event happens on the new topic.
    fireEvent("tournament:2:bracket", { tournament_id: 2, reason: "registration_changed" });
    act(() => {
      vi.advanceTimersByTime(2750);
    });

    // Must reflect ONLY registration_changed for tournament 2 -- not the
    // stale results_changed reason left over from tournament 1's topic.
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledTimes(1);
    expect(applyTournamentRealtimeUpdate).toHaveBeenCalledWith(
      expect.anything(),
      2,
      undefined,
      "registration_changed",
      undefined,
      2,
    );
  });
});
