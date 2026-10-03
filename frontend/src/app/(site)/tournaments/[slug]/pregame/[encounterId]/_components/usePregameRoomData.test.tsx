// @vitest-environment happy-dom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRealtimeStore } from "@/stores/realtime.store";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanKind, PickBanState } from "@/types/tournament.types";
import { usePregameRoomData } from "./usePregameRoomData";

const subscriptions = new Map<string, { event: (event?: unknown) => void; subscribed?: () => void }>();
const getState = vi.fn();
const getEncounter = vi.fn();
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/useRealtimeTopic", () => ({
  useRealtimeTopic: (topic: string | null, event: (event?: unknown) => void, _deps: unknown[], subscribed?: () => void) => {
    if (topic) subscriptions.set(topic, { event, subscribed });
  }
}));
vi.mock("@/hooks/useMapsCatalog", () => ({ useMapsCatalog: () => ({ data: [] }) }));
vi.mock("@/hooks/useHeroesCatalog", () => ({ useHeroesCatalog: () => ({ data: [] }) }));
vi.mock("@/services/captain.service", () => ({ default: { getMyRole: async () => ({ side: null }) } }));
vi.mock("@/services/pickBan.service", () => ({
  default: { getPickBanState: (...args: unknown[]) => getState(...args), markReady: async () => undefined }
}));
vi.mock("@/services/encounter.service", () => ({
  default: { getEncounter: (...args: unknown[]) => getEncounter(...args) }
}));
vi.mock("@/lib/notify", () => ({ notify: { apiError: vi.fn() } }));

declare global { var IS_REACT_ACT_ENVIRONMENT: boolean; }
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function state(paused = true): PickBanState {
  return {
    session: { id: 1, status: "active", paused_at: paused ? "2026-10-03T00:00:00Z" : null },
    is_complete: false,
    current_step_index: 0,
    current_round: 1,
    games: [],
    series: { home_wins: 0, away_wins: 0, played: 0, complete: false, official: null }
  } as unknown as PickBanState;
}

let states: Record<PickBanKind, PickBanState>;
let container: HTMLDivElement;
let root: Root;
let client: QueryClient;
function Harness({ encounterId }: { encounterId: number }) {
  const room = usePregameRoomData(encounterId);
  return <div>{room.mapState?.session?.paused_at ? "paused" : "running"}:{room.heroState?.session?.id ?? "no-hero"}:{room.encounter?.score?.home ?? 0}<span>{room.encounter?.matches.map((match) => match.log_name).join(",")}</span></div>;
}
async function advance(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}
async function render(encounterId = 42) {
  await act(async () => {
    root.render(<QueryClientProvider client={client}><Harness encounterId={encounterId} /></QueryClientProvider>);
  });
  await advance();
}
function signal(kind: PickBanKind) {
  act(() => subscriptions.get(`encounter:42:${kind === "map" ? "map-veto" : "pick-ban:hero"}`)?.event());
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, "random").mockReturnValue(0.5);
  vi.clearAllMocks();
  subscriptions.clear();
  useRealtimeStore.setState({ connectionState: "connected", topicErrors: {} });
  states = { map: state(), hero: state() };
  getState.mockImplementation(async (kind: PickBanKind) => states[kind]);
  getEncounter.mockResolvedValue({ id: 42, tournament_id: 3, score: { home: 0, away: 0 }, matches: [] } as unknown as Encounter);
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});
afterEach(() => {
  act(() => root.unmount());
  client.clear();
  container.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("pregame room refresh", () => {
  it("coalesces both topics without rereading encounter detail on blind draft updates", async () => {
    await render();
    states.map = { ...states.map, submissions: [{ id: 9, item_id: 21 }] } as PickBanState;
    signal("map");
    await advance(200);
    signal("hero");
    await advance(200);
    signal("map");
    await advance(100);
    expect(getState.mock.calls.map(([kind]) => kind)).toEqual(["map", "hero", "map", "hero"]);
    expect(getEncounter).toHaveBeenCalledTimes(1);
  });

  it("refreshes the visible encounter result once for a burst of game confirmation signals", async () => {
    await render();
    states.map = { ...states.map, series: { ...states.map.series!, home_wins: 1, played: 1 } };
    getEncounter.mockResolvedValue({ id: 42, score: { home: 1, away: 0 }, matches: [] } as unknown as Encounter);
    signal("map");
    signal("hero");
    signal("map");
    await advance(1600);
    expect(container.textContent).toBe("paused:1:1");
    expect(getEncounter).toHaveBeenCalledTimes(2);
  });

  it("stops paused polling, resumes on a signal, and continues settling active timeouts", async () => {
    await render();
    await advance(20_000);
    expect(getState).toHaveBeenCalledTimes(2);
    states.map = state(false);
    signal("map");
    await advance(1600);
    expect(container.textContent).toContain("running:");
    const before = getState.mock.calls.filter(([kind]) => kind === "map").length;
    states.map = { ...states.map, current_step_index: 1 };
    await advance(6500);
    expect(client.getQueryData<PickBanState>(["pregame-state", 42, "map"])?.current_step_index).toBe(1);
    expect(getState.mock.calls.filter(([kind]) => kind === "map").length).toBeGreaterThan(before);
  });

  it("checks paused rooms slowly while disconnected and catches a missed resume", async () => {
    await render();
    act(() => useRealtimeStore.setState({ connectionState: "reconnecting" }));
    await advance(10_000);
    expect(getState).toHaveBeenCalledTimes(2);
    states.map = state(false);
    await advance(25_000);
    expect(container.textContent).toContain("running:");
  });

  it("opens the coupled hero phase after a map timeout even without websocket delivery", async () => {
    states.map = state(false);
    states.hero = { ...state(), session: null, is_complete: true };
    await render();
    states.map = { ...states.map, is_complete: true, current_step_index: null };
    states.hero = { ...state(false), session: { ...state(false).session!, id: 2 } };
    await advance(7500);
    expect(container.textContent).toContain(":2:");
  });

  it("discards a pending old-room refresh on navigation and on unmount", async () => {
    await render();
    signal("map");
    await render(43);
    await advance(1600);
    expect(getState.mock.calls.filter(([, id]) => id === 42)).toHaveLength(2);
    const before = getState.mock.calls.length;
    act(() => subscriptions.get("encounter:43:map-veto")?.event());
    act(() => root.unmount());
    await advance(1600);
    expect(getState).toHaveBeenCalledTimes(before);
    root = createRoot(container);
  });

  it("catches up a completed room on resubscribe even though it has no active polling", async () => {
    states.map = { ...states.map, is_complete: true };
    states.hero = { ...states.hero, is_complete: true };
    await render();
    getEncounter.mockResolvedValue({ id: 42, score: { home: 2, away: 0 }, matches: [] } as unknown as Encounter);
    act(() => subscriptions.get("encounter:42:map-veto")?.subscribed?.());
    act(() => subscriptions.get("encounter:42:pick-ban:hero")?.subscribed?.());
    await advance(1600);
    expect(container.textContent).toBe("paused:1:2");
    expect(getEncounter).toHaveBeenCalledTimes(2);
  });

  it("refreshes a remotely parsed log without a changed game projection, only for this encounter", async () => {
    await render();
    getEncounter.mockResolvedValue({
      id: 42, tournament_id: 3, score: { home: 0, away: 0 },
      matches: [{ id: 91, log_name: "parsed.log" }]
    } as unknown as Encounter);
    const event = subscriptions.get("tournament:3:invalidation")!.event;
    act(() => event({
      data: { resources: ["tournament.encounters"], entity_ids: { encounter_ids: [99] } }
    }));
    await advance(1600);
    expect(getEncounter).toHaveBeenCalledTimes(1);
    expect(container.textContent).not.toContain("parsed.log");

    act(() => event({
      data: { resources: ["tournament.encounters", "tournament.standings"], entity_ids: { encounter_ids: [42] } }
    }));
    signal("map");
    act(() => event({
      data: { resources: ["tournament.encounters"], entity_ids: { encounter_ids: [42] } }
    }));
    await advance(1600);
    expect(container.textContent).toContain("parsed.log");
    expect(getEncounter).toHaveBeenCalledTimes(2);
  });
});
