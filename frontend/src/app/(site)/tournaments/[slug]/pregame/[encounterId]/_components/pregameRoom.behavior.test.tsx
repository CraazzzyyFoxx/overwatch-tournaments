// @vitest-environment happy-dom
//
// Covers the unified pre-game room's NEW contract over the retired
// VetoRoom/HeroBanRoom pair: the readiness gate (waiting screen, ready
// button, captain-only visibility) and sequential map -> hero phase
// selection. Grid/timeline grouping logic is already exhaustively covered by
// pick-ban-model.test.ts against the same unmodified components.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import en from "@/i18n/messages/en.json";
import type { Encounter } from "@/types/encounter.types";
import type { PickBanEntry, PickBanSession, PickBanState } from "@/types/tournament.types";

import { PregameRoom } from "./PregameRoom";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getPickBanState = vi.fn();
const performPickBanAction = vi.fn();
const undoLastAction = vi.fn();
const markReady = vi.fn();
const getEncounter = vi.fn();
const getAllMaps = vi.fn();
const getAllHeroes = vi.fn();
const getMyRole = vi.fn();
const getReports = vi.fn();
const submitReport = vi.fn();
const routerPush = vi.fn();
/** The room's `?from=` param, rewritten per test. */
let search = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useSearchParams: () => search,
  useRouter: () => ({ push: (...args: unknown[]) => routerPush(...args) })
}));

vi.mock("@/services/pickBan.service", () => ({
  default: {
    getPickBanState: (...args: unknown[]) => getPickBanState(...args),
    performPickBanAction: (...args: unknown[]) => performPickBanAction(...args),
    markReady: (...args: unknown[]) => markReady(...args),
    undoLastAction: (...args: unknown[]) => undoLastAction(...args),
    electOpener: vi.fn(),
    reportMap: vi.fn()
  }
}));
vi.mock("@/services/captain.service", () => ({
  default: {
    getMyRole: (...args: unknown[]) => getMyRole(...args),
    getReports: (...args: unknown[]) => getReports(...args),
    submitReport: (...args: unknown[]) => submitReport(...args)
  }
}));
vi.mock("@/services/encounter.service", () => ({
  default: { getEncounter: (...args: unknown[]) => getEncounter(...args) }
}));
vi.mock("@/services/map.service", () => ({
  default: { getAll: (...args: unknown[]) => getAllMaps(...args) }
}));
vi.mock("@/services/hero.service", () => ({
  default: { getAll: (...args: unknown[]) => getAllHeroes(...args) }
}));
/** Topic -> the room's handler, so a test can fire what the hub would push. */
const realtimeHandlers = new Map<string, () => void>();
vi.mock("@/hooks/useRealtimeTopic", () => ({
  useRealtimeTopic: (topic: string, onEvent: () => void) => {
    realtimeHandlers.set(topic, onEvent);
  }
}));
const usePermissionsMock = vi.fn(() => ({
  isSuperuser: false,
  isWorkspaceAdmin: () => false,
  hasWorkspacePermission: () => false
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => usePermissionsMock()
}));
vi.mock("@/lib/notify", () => ({
  notify: { apiError: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn() }
}));

const ROOM = en.pickBan.room;

const MAPS = [21, 22, 23].map((id) => ({ id, name: `Map ${id}`, image_path: "" }));
const HEROES = [101, 102, 103].map((id) => ({
  id,
  name: `Hero ${id}`,
  slug: `hero-${id}`,
  image_path: "",
  type: "Damage",
  role: "damage"
}));

function encounter(): Encounter {
  return {
    id: 4242,
    home_team: { id: 7, name: "Bright Wolves" },
    away_team: { id: 8, name: "Quiet Foxes" },
    tournament: { id: 3, workspace_id: 1 }
  } as unknown as Encounter;
}

function entry(overrides: Partial<PickBanEntry>): PickBanEntry {
  return {
    id: 1,
    item_id: 21,
    round: null,
    order: 0,
    action_index: null,
    picked_by: null,
    protected_by: null,
    team_id: null,
    status: "available",
    ...overrides
  };
}

function session(overrides: Partial<PickBanSession> = {}): PickBanSession {
  return {
    id: 1,
    kind: "map",
    status: "active",
    first_side: "home",
    awaiting_choice: false,
    pending_loser_side: null,
    seed_source: "bracket_slot",
    home_seed: 1,
    away_seed: 4,
    turn_timer_seconds: null,
    slot_reserves: null,
    started_at: "2026-08-01T10:00:00Z",
    current_step_started_at: null,
    ...overrides
  };
}

function readyState(overrides: Partial<PickBanState>): PickBanState {
  return {
    session: session(),
    readiness: { home: true, away: true },
    sequence: [],
    pool: [],
    viewer_side: "home",
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: 0,
    current_step: null,
    expected_action: null,
    turn_side: null,
    current_round: null,
    is_complete: false,
    ...overrides
  };
}

function unavailableState(
  reason: NonNullable<PickBanState["reason"]>,
  readiness = { home: false, away: false }
): PickBanState {
  return {
    session: null,
    reason,
    readiness,
    sequence: [],
    pool: [],
    viewer_side: null,
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: null,
    current_step: null,
    expected_action: null,
    turn_side: null,
    current_round: null,
    is_complete: false
  };
}

let container: HTMLDivElement;
let root: Root;
let scrollIntoView: Mock;

beforeEach(() => {
  vi.clearAllMocks();
  getAllMaps.mockResolvedValue({ results: MAPS });
  getAllHeroes.mockResolvedValue({ results: HEROES });
  getEncounter.mockResolvedValue(encounter());
  getMyRole.mockResolvedValue({ side: null });
  getReports.mockResolvedValue({ reports: [], form: undefined });
  realtimeHandlers.clear();
  search = new URLSearchParams();
  usePermissionsMock.mockReturnValue({
    isSuperuser: false,
    isWorkspaceAdmin: () => false,
    hasWorkspacePermission: () => false
  });
  scrollIntoView = vi.fn();
  Element.prototype.scrollIntoView = scrollIntoView;
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

async function render(props: { seriesReport?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          <PregameRoom encounterId={4242} {...props} />
        </NextIntlClientProvider>
      </QueryClientProvider>
    );
  });
  await settle();
}

/** Routes `getPickBanState(kind, id)` mock calls to per-kind canned responses. */
function mockStates(map: PickBanState, hero: PickBanState) {
  getPickBanState.mockImplementation((kind: string) =>
    Promise.resolve(kind === "map" ? map : hero)
  );
}

describe("readiness gate", () => {
  it("shows the waiting screen when a configured kind reports not_ready", async () => {
    mockStates(unavailableState("not_ready"), unavailableState("not_configured"));
    await render();

    expect(document.body.textContent).toContain(ROOM.notReadyTitle);
    expect(document.body.textContent).toContain(ROOM.notReadyHint);
  });

  it("shows the ready button for a captain who has not confirmed yet", async () => {
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      unavailableState("not_ready", { home: false, away: true }),
      unavailableState("not_configured")
    );
    await render();

    const button = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === ROOM.ready.button
    );
    expect(button).toBeTruthy();

    await act(async () => {
      button?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(markReady).toHaveBeenCalledWith(4242);
  });

  it("shows a waiting-on-opponent message instead of a button once the viewer's own side is ready", async () => {
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      unavailableState("not_ready", { home: true, away: false }),
      unavailableState("not_configured")
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.ready.confirmed);
    expect(document.body.textContent).toContain(ROOM.ready.waitingOpponent);
    const button = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === ROOM.ready.button
    );
    expect(button).toBeUndefined();
  });

  it("hides the ready button entirely for a non-captain spectator", async () => {
    getMyRole.mockResolvedValue({ side: null });
    mockStates(unavailableState("not_ready"), unavailableState("not_configured"));
    await render();

    const button = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === ROOM.ready.button
    );
    expect(button).toBeUndefined();
  });

  it("renders the real room behind the gate — matchup and per-side state, no skeletons", async () => {
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      unavailableState("not_ready", { home: true, away: false }),
      unavailableState("not_configured")
    );
    await render();

    // The header is real, not a placeholder: both teams are on screen.
    expect(document.body.textContent).toContain("Bright Wolves");
    expect(document.body.textContent).toContain("Quiet Foxes");
    // Each side says where it stands, rather than one modal line for both.
    expect(document.body.textContent).toContain(ROOM.ready.stateReady);
    expect(document.body.textContent).toContain(ROOM.ready.statePending);
    // Nothing pretends to be loading: this state only clears when a human in
    // another browser confirms, so a shimmer would never resolve.
    expect(document.body.querySelector(".animate-pulse")).toBeNull();
  });
});

describe("closed-door copy", () => {
  it("shows the generic not-configured card when neither kind applies", async () => {
    mockStates(unavailableState("not_configured"), unavailableState("not_configured"));
    await render();

    expect(document.body.textContent).toContain(ROOM.notConfiguredTitle);
    expect(document.body.textContent).toContain(ROOM.notConfiguredHint);
  });

  it("surfaces a misconfigured map's own reason instead of skipping to hero", async () => {
    mockStates(
      unavailableState("slot_underfilled"),
      readyState({ session: session({ kind: "hero" }) })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.slotUnderfilledTitle);
  });
});

describe("phase selection", () => {
  it("renders the map phase first when both kinds are configured", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: ["ban_home", "ban_away"],
        pool: [entry({ id: 1, item_id: 21 }), entry({ id: 2, item_id: 22 })]
      }),
      readyState({ session: session({ kind: "hero" }) })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.map.title);
    expect(document.body.textContent).toContain(`Map 21`);
    // Phase strip names all three steps of the round, current on map.
    expect(document.body.textContent).toContain(ROOM.phase.map);
    expect(document.body.textContent).toContain(ROOM.phase.hero);
    expect(document.body.textContent).toContain(ROOM.phase.report);
  });

  it("advances to the hero phase once this round's map is picked", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1 })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.hero.title);
    // Hero Pool tiles are icon-only now -- the name surfaces as the button's
    // accessible name/tooltip, not as visible text content.
    expect(document.body.querySelector('button[title="Hero 101"]')).toBeTruthy();
  });

  it("offers the undo beside the pool a captain is still acting on", async () => {
    // The other placement: mid-sequence, where the misclick happens. Both read
    // the same server-side `undo` block, so neither screen holds its own idea
    // of what is pending.
    getMyRole.mockResolvedValue({ side: "away" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_home", "ban_away"],
        viewer_side: "away",
        pool: [
          entry({
            id: 3,
            item_id: 101,
            round: 1,
            status: "banned",
            picked_by: "home",
            action_index: 0
          }),
          entry({ id: 4, item_id: 102, round: 1 })
        ],
        undo: { requested_by: null, item_ids: [101], action: "ban", side: "home" }
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.hero.title);
    const ask = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.undo.ask)
    );
    expect(ask).toBeTruthy();

    await act(async () => ask!.click());
    await settle();

    expect(undoLastAction).toHaveBeenCalledWith("hero", 4242, true);
  });

  it("greys out and disables the roles the ban rule has spent, but never the protect", async () => {
    // `unique_attribute: "role"` = one action per role per side per round. Home
    // has banned a tank, so its second tank ban is a click the server would
    // reject -- the tile says so instead of letting the captain find out.
    getAllHeroes.mockResolvedValue({
      results: [
        { id: 201, name: "Tank A", type: "Tank", role: "tank", image_path: "" },
        { id: 202, name: "Tank B", type: "Tank", role: "tank", image_path: "" },
        { id: 203, name: "Support A", type: "Support", role: "support", image_path: "" }
      ]
    });
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_home", "ban_home"],
        viewer_side: "home",
        viewer_can_act: true,
        allowed_actions: ["ban"],
        expected_action: "ban",
        turn_side: "home",
        current_round: 1,
        unique_attribute: "role",
        pool: [
          entry({
            id: 3,
            item_id: 201,
            round: 1,
            status: "banned",
            picked_by: "home",
            action_index: 0
          }),
          entry({ id: 4, item_id: 202, round: 1 }),
          entry({ id: 5, item_id: 203, round: 1 })
        ]
      })
    );
    await render();

    const tile = (name: string) =>
      document.body.querySelector<HTMLButtonElement>(`button[aria-label^="${name}"]`);
    // The second tank is inert and greyed; the support is untouched.
    expect(tile("Tank B")?.disabled).toBe(true);
    expect(tile("Tank B")?.className).toContain("grayscale");
    expect(tile("Tank B")?.title).toBe(ROOM.rule.blocked);
    expect(tile("Support A")?.disabled).toBe(false);
    expect(tile("Support A")?.className).not.toContain("grayscale");
  });

  it("greys a pointless protect without taking the click away", async () => {
    // Away banned a tank, so they cannot ban a second one: home protecting a
    // tank defends against nothing. A hint, not a rule -- still clickable.
    getAllHeroes.mockResolvedValue({
      results: [
        { id: 201, name: "Tank A", type: "Tank", role: "tank", image_path: "" },
        { id: 202, name: "Tank B", type: "Tank", role: "tank", image_path: "" },
        { id: 203, name: "Support A", type: "Support", role: "support", image_path: "" }
      ]
    });
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_away", "protect_home"],
        viewer_side: "home",
        viewer_can_act: true,
        allowed_actions: ["protect"],
        expected_action: "protect",
        turn_side: "home",
        current_round: 1,
        unique_attribute: "role",
        pool: [
          entry({
            id: 3,
            item_id: 201,
            round: 1,
            status: "banned",
            picked_by: "away",
            action_index: 0
          }),
          entry({ id: 4, item_id: 202, round: 1 }),
          entry({ id: 5, item_id: 203, round: 1 })
        ]
      })
    );
    await render();

    const tank = document.body.querySelector<HTMLButtonElement>('button[aria-label^="Tank B"]');
    expect(tank?.disabled).toBe(false);
    expect(tank?.className).toContain("grayscale");
    expect(tank?.title).toBe(ROOM.rule.pointless);
  });

  it("greys out and disables a hero this side already banned earlier in the series", async () => {
    // `no_repeat_scope=encounter_same_side`: one pool, two sides, and only the
    // side that spent the ban is barred -- so the item STAYS in the round's pool
    // and the rule is enforced per action. Without this the only feedback was
    // the 400 that arrives after the click.
    getAllHeroes.mockResolvedValue({
      results: [
        { id: 201, name: "Tank A", type: "Tank", role: "tank", image_path: "" },
        { id: 203, name: "Support A", type: "Support", role: "support", image_path: "" }
      ]
    });
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 22, round: 2, status: "picked", action_index: 5 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_home"],
        viewer_side: "home",
        viewer_can_act: true,
        allowed_actions: ["ban"],
        expected_action: "ban",
        turn_side: "home",
        current_round: 2,
        // Home banned Tank A back in round 1; round 2's pool offers it again.
        repeat_banned: [201],
        pool: [entry({ id: 3, item_id: 201, round: 2 }), entry({ id: 4, item_id: 203, round: 2 })]
      })
    );
    await render();

    const tile = (name: string) =>
      document.body.querySelector<HTMLButtonElement>(`button[aria-label^="${name}"]`);
    expect(tile("Tank A")?.disabled).toBe(true);
    expect(tile("Tank A")?.className).toContain("grayscale");
    expect(tile("Tank A")?.title).toBe(ROOM.rule.repeat);
    expect(tile("Support A")?.disabled).toBe(false);
    expect(tile("Support A")?.className).not.toContain("grayscale");
  });

  it("still lets this side protect a hero it already banned earlier in the series", async () => {
    // The ledger is BAN memory: `repeat_banned` bars a second ban by this side,
    // never a protect. The OPPONENT can still ban the hero, so protecting it is
    // both legal and the whole point -- the grid used to grey it out on every
    // step, protect included, leaving the immunity unreachable.
    getAllHeroes.mockResolvedValue({
      results: [
        { id: 201, name: "Tank A", type: "Tank", role: "tank", image_path: "" },
        { id: 203, name: "Support A", type: "Support", role: "support", image_path: "" }
      ]
    });
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 22, round: 2, status: "picked", action_index: 5 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["protect_home"],
        viewer_side: "home",
        viewer_can_act: true,
        allowed_actions: ["protect"],
        expected_action: "protect",
        turn_side: "home",
        current_round: 2,
        repeat_banned: [201],
        pool: [entry({ id: 3, item_id: 201, round: 2 }), entry({ id: 4, item_id: 203, round: 2 })]
      })
    );
    await render();

    const tank = document.body.querySelector<HTMLButtonElement>('button[aria-label^="Tank A"]');
    expect(tank?.disabled).toBe(false);
    expect(tank?.className).not.toContain("grayscale");
  });

  it("charts the series' play order once, in the header", async () => {
    // The pool card used to repeat the whole play order under the grid — the
    // same maps the header's series filmstrip already charts, twice on one
    // screen. These two are the only ordered lists the room draws.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        viewer_side: "home",
        sequence: ["ban_home", "ban_away", "decider"],
        current_round: 2,
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2 }),
          entry({ id: 3, item_id: 23, round: 2 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 4, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.map.title);
    expect(
      Array.from(document.body.querySelectorAll("ol")).map((list) =>
        list.getAttribute("aria-label")
      )
    ).toEqual([ROOM.phase.rail, ROOM.series.label]);
  });

  it("draws a protected hero as protected, never as banned", async () => {
    getAllHeroes.mockResolvedValue({
      results: [
        { id: 201, name: "Tank A", type: "Tank", role: "tank", image_path: "" },
        { id: 202, name: "Tank B", type: "Tank", role: "tank", image_path: "" }
      ]
    });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["protect_home", "ban_away"],
        current_round: 1,
        pool: [
          entry({
            id: 3,
            item_id: 201,
            round: 1,
            status: "protected",
            protected_by: "home",
            action_index: 0
          }),
          entry({
            id: 4,
            item_id: 202,
            round: 1,
            status: "banned",
            picked_by: "away",
            action_index: 1
          })
        ]
      })
    );
    await render();

    const protectedTile = document.body.querySelector<HTMLButtonElement>(
      'button[aria-label^="Tank A"]'
    );
    const bannedTile = document.body.querySelector<HTMLButtonElement>(
      'button[aria-label^="Tank B"]'
    );
    // The banned one is crossed out and drained of colour; the protected one is
    // neither -- it is still in the game, and it wears a shield instead.
    expect(bannedTile?.querySelector(".lucide-ban")).toBeTruthy();
    expect(bannedTile?.innerHTML).toContain("grayscale");
    expect(protectedTile?.querySelector(".lucide-ban")).toBeNull();
    expect(protectedTile?.querySelector(".lucide-shield")).toBeTruthy();
    expect(protectedTile?.innerHTML).not.toContain("grayscale");
  });

  it("asks for the map's result once its heroes are banned", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    expect(document.body.textContent).toContain("Map 21");
    expect(document.body.textContent).toContain(ROOM.mapResult.report);
    // Neither side has filed yet, and no score is on screen to copy.
    expect(document.body.textContent).toContain(
      ROOM.mapResult.pending.replace("{team}", "Bright Wolves")
    );
  });

  it("carries this map's hero bans onto the result screen, split by side", async () => {
    // The room renders one phase at a time, so the moment the hero grid closes
    // this is the only screen still naming what was banned -- and it is the
    // screen the captains are on while setting up the lobby.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home", "ban_away", "protect_away"],
        pool: [
          entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by: "home" }),
          entry({ id: 4, item_id: 102, round: 1, status: "banned", picked_by: "away" }),
          entry({ id: 5, item_id: 103, round: 1, status: "protected", protected_by: "away" }),
          // Another round's ban: the lobby for THIS map must not carry it.
          entry({ id: 6, item_id: 104, round: 2, status: "banned", picked_by: "home" })
        ]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.heroBans.eyebrow);
    const sides = Array.from(document.body.querySelectorAll<HTMLElement>("[data-hero-bans]"));
    expect(sides.map((tile) => tile.dataset.heroBans)).toEqual(["home", "away"]);
    expect(sides[0].textContent).toContain("Hero 101");
    expect(sides[1].textContent).toContain("Hero 102");
    expect(sides[1].textContent).toContain("Hero 103");
    expect(sides[0].textContent).not.toContain("Hero 102");
    expect(document.body.textContent).not.toContain("Hero 104");
    // A protect is not a ban: it is marked apart and sorted after them, because
    // a protected hero must stay ENABLED in the lobby.
    const awayRows = Array.from(sides[1].querySelectorAll<HTMLElement>("[data-hero-action]"));
    expect(awayRows.map((row) => row.dataset.heroAction)).toEqual(["ban", "protect"]);
    expect(awayRows[1].textContent).toContain(ROOM.heroBans.state.protect);
  });

  it("leaves the result screen without a bans block when no heroes were banned", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      unavailableState("not_configured", { home: true, away: true })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.mapResult.report);
    expect(document.body.textContent).not.toContain(ROOM.heroBans.eyebrow);
    expect(document.body.querySelector("[data-hero-bans]")).toBeNull();
  });

  it("offers the hero undo under the bans, and asks the opponent to agree", async () => {
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: "home",
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by: "home" })],
        undo: { requested_by: null, item_ids: [101], action: "ban", side: "home" }
      })
    );
    await render();

    const ask = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.undo.ask)
    );
    expect(ask).toBeTruthy();
    // The affordance names what goes back, so "undo" is never a blind button.
    expect(document.body.textContent).toContain(ROOM.undo.label);

    await act(async () => ask!.click());
    await settle();

    expect(undoLastAction).toHaveBeenCalledWith("hero", 4242, true);
  });

  it("shows the opponent's open request with agree and decline", async () => {
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: "home",
        sequence: ["ban_away"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by: "away" })],
        undo: { requested_by: "away", item_ids: [101], action: "ban", side: "away" }
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.undo.asked.replace("{team}", "Quiet Foxes"));
    const agree = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.undo.agree)
    );
    const decline = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.undo.decline)
    );
    expect(agree).toBeTruthy();
    expect(decline).toBeTruthy();

    await act(async () => decline!.click());
    await settle();

    expect(undoLastAction).toHaveBeenCalledWith("hero", 4242, false);
  });

  it("tells the asking side it is waiting, and offers no agree button", async () => {
    getMyRole.mockResolvedValue({ side: "home" });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: "home",
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by: "home" })],
        undo: { requested_by: "home", item_ids: [101], action: "ban", side: "home" }
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.undo.waiting.replace("{team}", "Quiet Foxes"));
    expect(document.body.textContent).toContain(ROOM.undo.withdraw);
    expect(document.body.textContent).not.toContain(ROOM.undo.agree);
  });

  it("keeps the undo affordance off the screen when nothing can be taken back", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: "home",
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by: "home" })],
        undo: { requested_by: null, item_ids: [], action: null, side: null }
      })
    );
    await render();

    expect(document.body.textContent).not.toContain(ROOM.undo.label);
    expect(document.body.textContent).not.toContain(ROOM.undo.ask);
  });

  it("shows the viewer their own filed score while the opponent's stays sealed", async () => {
    // Two independent claims that reconcile: revealing the first would turn the
    // second into a copy of it. The viewer's own numbers are theirs already.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })],
        map_reports: [{ map_id: 21, map_index: 1, side: "home", home_score: 3, away_score: 1 }]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    // Own claim carries the digits the viewer typed; the opponent has filed
    // nothing, so its tile is the empty "waiting" state and the verdict still
    // reads "awaiting both".
    const claims = Array.from(document.body.querySelectorAll<HTMLElement>("[data-claim]"));
    expect(claims.map((tile) => tile.dataset.claim)).toEqual(["filed", "waiting"]);
    const visibleSlab = (tile: HTMLElement) =>
      Array.from(tile.querySelectorAll<HTMLElement>(".tabular-nums"))
        .map((slab) => slab.textContent ?? "")
        .join("");
    expect(visibleSlab(claims[0])).toBe("3:1");
    expect(visibleSlab(claims[1])).toBe("?:?");
    expect(document.body.textContent).toContain(ROOM.mapResult.verdict.waiting);
    expect(document.body.textContent).toContain(ROOM.mapResult.amend);
  });

  it("charts every settled map of the series with its confirmed score", async () => {
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 1, away: 0 },
      matches: [{ map_id: 21, map_index: 1, score: { home: 3, away: 1 } }]
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 2, status: "banned" })]
      })
    );
    await render();

    const strip = document.body.querySelector(`ol[aria-label="${ROOM.series.label}"]`);
    expect(strip).toBeTruthy();
    // Map 1 is settled and carries its confirmed score; map 2 is the one whose
    // result the loop is still waiting on.
    const items = Array.from(strip?.querySelectorAll("li") ?? []);
    expect(items).toHaveLength(2);
    expect(items[0].textContent).toContain("Map 21");
    expect(items[0].textContent).toContain("3:1");
    expect(items[1].textContent).toContain("Map 22");
    expect(items[1].textContent).toContain(ROOM.series.awaiting);
    expect(items[1].textContent).not.toMatch(/\d:\d/);
  });

  it("never scores a map the series has not played, even with a Match row for it", async () => {
    // The regression: `Match` rows exist for maps a log parser touched or that
    // were pre-created at 0:0, so keying "settled" off `match != null` printed
    // a 0:0 nobody scored on an unreached map — and a score on the very map the
    // panel below was still asking both captains to report.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 0, away: 0 },
      matches: [
        { map_id: 21, map_index: 1, score: { home: 1, away: 0 } },
        { map_id: 23, map_index: 3, score: { home: 0, away: 0 } }
      ]
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        // A slots veto settles the whole series at once: all three are `picked`,
        // none `played`. Map 21 is the one being played and reported right now.
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 }),
          entry({ id: 3, item_id: 23, round: 3, status: "picked", action_index: 8 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 4, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    const items = Array.from(
      document.body.querySelectorAll(`ol[aria-label="${ROOM.series.label}"] li`)
    );
    expect(items).toHaveLength(3);
    // Not one of them is settled, so not one of them shows digits — including
    // map 21 and map 23, which both HAVE a Match row.
    for (const item of items) expect(item.textContent).not.toMatch(/\d:\d/);
    // Only the first unplayed map is the one being awaited; the rest are simply
    // maps of the series that have not been reached.
    expect(items[0].textContent).toContain(ROOM.series.awaiting);
    expect(items[1].textContent).toContain(ROOM.series.upcoming);
    expect(items[2].textContent).toContain(ROOM.series.upcoming);
  });

  it("keeps an earlier play's claims and score off a map the series plays twice", async () => {
    // A slot config may list the same map in every round, and with
    // `no_repeat_scope=none` nothing stops the series from playing it three
    // times. Keyed on `map_id` alone, the third play inherited the first play's
    // two agreeing claims — so the room told both captains the map was already
    // locked in — and both settled positions printed the same score, the one
    // from whichever Match row happened to come first.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 1, away: 1 },
      matches: [
        { map_id: 21, map_index: 1, score: { home: 2, away: 1 } },
        { map_id: 21, map_index: 2, score: { home: 0, away: 2 } }
      ]
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 21, round: 2, status: "played", action_index: 5 }),
          entry({ id: 3, item_id: 21, round: 3, status: "picked", action_index: 8 })
        ],
        map_reports: [
          { map_id: 21, map_index: 1, side: "home", home_score: 2, away_score: 1 },
          { map_id: 21, map_index: 1, side: "away", home_score: 2, away_score: 1 },
          { map_id: 21, map_index: 2, side: "home", home_score: 0, away_score: 2 },
          { map_id: 21, map_index: 2, side: "away", home_score: 0, away_score: 2 }
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 4, item_id: 101, round: 3, status: "banned" })]
      })
    );
    await render();

    // Round 3 of map 21 is awaiting its result: neither claim is in yet.
    const claims = Array.from(document.body.querySelectorAll<HTMLElement>("[data-claim]"));
    expect(claims.map((tile) => tile.dataset.claim)).toEqual(["waiting", "waiting"]);
    expect(document.body.textContent).toContain(ROOM.mapResult.verdict.waiting);
    expect(document.body.textContent).toContain(ROOM.mapResult.report);

    // Each settled position carries ITS OWN score; the third play has none.
    const items = Array.from(
      document.body.querySelectorAll(`ol[aria-label="${ROOM.series.label}"] li`)
    );
    expect(items).toHaveLength(3);
    expect(items[0].textContent).toContain("2:1");
    expect(items[1].textContent).toContain("0:2");
    expect(items[2].textContent).toContain(ROOM.series.awaiting);
    expect(items[2].textContent).not.toMatch(/\d:\d/);
  });

  it("refetches the encounter when a map result lands over the wire", async () => {
    // The series score lives on the encounter, not in the pool, so the captain
    // who reported FIRST only sees it move on a refetch of THAT query — the
    // realtime handler used to refresh the two pick-ban states and nothing else.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();
    const before = getEncounter.mock.calls.length;

    realtimeHandlers.get("encounter:4242:map-veto")?.();
    await settle();

    expect(getEncounter.mock.calls.length).toBeGreaterThan(before);
  });

  it("stays on the hero phase while the hero round for the pending map is still catching up", async () => {
    // Map 2 was just picked; the hero session still only holds round 1, whose
    // steps are all taken. Jumping to "report" here would skip map 2's bans.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.hero.title);
    expect(document.body.textContent).not.toContain(ROOM.mapResult.report);
  });

  it("names who the room is waiting on when a round needs its opener elected", async () => {
    // `result_loser_choice`: round 2 does not exist until the losing captain
    // names its opener, so the room shows a finished round 1 with nothing to
    // click. Only that captain got the modal — everyone else (the winner, a
    // spectator, the organizer holding the reset button) saw a hung room.
    getMyRole.mockResolvedValue({ side: null });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: null,
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({
          kind: "hero",
          status: "completed",
          awaiting_choice: true,
          pending_loser_side: "away"
        }),
        is_complete: true,
        viewer_side: null,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(
      ROOM.electOpener.waiting.replace("{team}", "Quiet Foxes")
    );
  });

  /** A series with every map picked, banned, played and reconciled. */
  function settledSeries(viewerSide: "home" | "away" | null) {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: viewerSide,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: viewerSide,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
  }

  it("asks a captain for the series report once nothing is left to pick or ban", async () => {
    // The room used to end on "nothing left to decide" and send captains off to
    // hunt for the report dialog elsewhere. The form belongs here, prefilled
    // with the score the room itself just collected map by map.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 1,
      score: { home: 1, away: 0 }
    } as unknown as Encounter);
    settledSeries("home");
    await render();

    expect(document.body.textContent).toContain(ROOM.finalReport.title);
    expect(document.body.textContent).not.toContain(ROOM.seriesDone.title);
    // Prefilled from the encounter's own series score, not left at 0:0.
    const score = (label: string) =>
      document.body.querySelector<HTMLInputElement>(`input[aria-label="Score for ${label}"]`)
        ?.value;
    expect(score("Bright Wolves")).toBe("1");
    expect(score("Quiet Foxes")).toBe("0");
    expect(document.body.textContent).toContain(en.matchReport.submit);
  });

  it("keeps the settled notice for anyone who captains neither side", async () => {
    // A spectator, or an admin who is not a captain, has no report to file: the
    // captain report is per-team.
    settledSeries(null);
    await render();

    expect(document.body.textContent).toContain(ROOM.seriesDone.title);
    expect(document.body.textContent).not.toContain(ROOM.finalReport.title);
  });

  it("never asks a scrim captain for a series report", async () => {
    // A scrim publishes no result, and the report form is built from a
    // per-tournament config the scrims container does not have — so a captain who
    // WOULD be asked in a tournament gets the closing notice instead, with its
    // own line: "the result is with the organizers now" names a role a scrim has
    // nobody in.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 1,
      score: { home: 1, away: 0 }
    } as unknown as Encounter);
    settledSeries("home");
    await render({ seriesReport: false });

    expect(document.body.textContent).toContain(ROOM.seriesDone.title);
    expect(document.body.textContent).toContain(ROOM.seriesDone.hintNoReport);
    expect(document.body.textContent).not.toContain(ROOM.finalReport.title);
    expect(document.body.textContent).not.toContain(ROOM.seriesDone.hint);
    // The form itself is gone, not merely hidden behind a heading.
    expect(document.body.textContent).not.toContain(en.matchReport.submit);
    expect(document.body.querySelector('input[aria-label="Score for Bright Wolves"]')).toBeNull();
  });

  it("names the winner on the closing screen when there is no report to file", async () => {
    // "Who won and that's it" is the whole point of a scrim's closing screen:
    // ending a finished series without saying how it ended is what made the room
    // feel broken once the report was removed. Read off the encounter's own
    // running score, which the per-map reports advance.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 2, away: 1 }
    } as unknown as Encounter);
    settledSeries("home");
    await render({ seriesReport: false });

    expect(document.body.textContent).toContain("Bright Wolves won the series 2:1");
  });

  it("replays every map's hero bans on the closing screen", async () => {
    // The closing screen used to be the one place in the loop that named
    // nothing about the heroes: `heroActions` keys off the PENDING map, and by
    // the time the series is done there is none, so the record of what each map
    // was played under vanished with the last grid that closed.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 2, away: 0 }
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: null,
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "played", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: null,
        sequence: ["ban_home", "ban_away"],
        pool: [
          entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by: "home" }),
          entry({ id: 4, item_id: 102, round: 2, status: "banned", picked_by: "away" })
        ]
      })
    );
    await render();

    const record = document.body.querySelector<HTMLElement>("[data-hero-record]");
    const text = record?.textContent ?? "";
    expect(document.body.textContent).toContain(ROOM.heroBans.seriesTitle);
    // One block per map, each captioned by its own round and map — not one
    // caption claiming to describe "this map" on a screen where there is none.
    expect(text).toContain("Round 1");
    expect(text).toContain("Round 2");
    expect(text).toContain("Map 21");
    expect(text).toContain("Map 22");
    expect(text).toContain("Hero 101");
    expect(text).toContain("Hero 102");
    expect(record?.querySelectorAll("[data-hero-bans]")).toHaveLength(4);
    // The lobby-setup hint belongs to a map about to be played, never here.
    expect(text).not.toContain(ROOM.heroBans.hint);
    expect(text).not.toContain(ROOM.heroBans.seriesEyebrow);
  });

  it("states a flat hero pool once, not once per map", async () => {
    // A round-less pool bans for the whole series; repeating it under every map
    // would invent per-map decisions nobody made.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 2, away: 0 }
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: null,
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "played", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: null,
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: null, status: "banned", picked_by: "home" })]
      })
    );
    await render();

    const record = document.body.querySelector<HTMLElement>("[data-hero-record]");
    expect(record?.textContent).toContain(ROOM.heroBans.seriesEyebrow);
    // No per-map caption inside the record: the set covered every map, so
    // naming one of them would be a claim nobody made.
    expect(record?.textContent).not.toContain("Map 21");
    expect(record?.textContent).not.toContain("Map 22");
    // Two sides, one block — not two blocks of two sides.
    expect(record?.querySelectorAll("[data-hero-bans]")).toHaveLength(2);
  });

  it("leaves the closing screen without a bans block when nothing was banned", async () => {
    settledSeries(null);
    getPickBanState.mockImplementation(async (kind: "map" | "hero") =>
      kind === "map"
        ? readyState({
            session: session({ kind: "map" }),
            is_complete: true,
            viewer_side: null,
            pool: [entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 })]
          })
        : readyState({
            session: session({ kind: "hero" }),
            is_complete: true,
            viewer_side: null,
            sequence: ["ban_home"],
            pool: [entry({ id: 3, item_id: 101, round: 1, status: "available" })]
          })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.seriesDone.title);
    expect(document.body.textContent).not.toContain(ROOM.heroBans.seriesTitle);
    expect(document.body.querySelector("[data-hero-bans]")).toBeNull();
  });

  it("charts a played map's score from the captains' claims when no Match row exists", async () => {
    // A scrim writes no `matches.match` rows at all, so the filmstrip's score
    // has to come from the agreed claims instead — otherwise every map of a
    // scrim showed as played with nothing on it, which is what made the loop
    // look stuck even though it was advancing correctly.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 1, away: 0 },
      matches: []
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ],
        map_reports: [
          { map_id: 21, map_index: 1, side: "home", home_score: 2, away_score: 1 },
          { map_id: 21, map_index: 1, side: "away", home_score: 2, away_score: 1 }
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: "home",
        sequence: ["ban_home"],
        pool: [
          entry({ id: 3, item_id: 101, round: 1, status: "banned" }),
          entry({ id: 4, item_id: 102, round: 2, status: "banned" })
        ]
      })
    );
    await render({ seriesReport: false });

    const items = Array.from(
      document.body.querySelectorAll(`ol[aria-label="${ROOM.series.label}"] li`)
    );
    expect(items[0].textContent).toContain("2:1");
    // Map 2 is picked but not played: still no score, and still the one awaited.
    expect(items[1].textContent).toContain(ROOM.series.awaiting);
    expect(items[1].textContent).not.toMatch(/\d:\d/);
  });

  it("shows no score for a map whose captains disagree", async () => {
    // A dispute is exactly when there is no agreed number, and the server will
    // not advance the series either — inventing one here would tell the captains
    // the map was settled.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      matches: []
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_side: "home",
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "played", action_index: 2 })],
        map_reports: [
          { map_id: 21, map_index: 1, side: "home", home_score: 2, away_score: 1 },
          { map_id: 21, map_index: 1, side: "away", home_score: 0, away_score: 2 }
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_side: "home",
        sequence: ["ban_home"],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render({ seriesReport: false });

    const items = Array.from(
      document.body.querySelectorAll(`ol[aria-label="${ROOM.series.label}"] li`)
    );
    expect(items[0].textContent).not.toMatch(/\d:\d/);
  });

  it("goes straight to hero when the encounter has no map rule set at all", async () => {
    mockStates(
      unavailableState("not_configured"),
      readyState({ session: session({ kind: "hero" }), pool: [entry({ id: 3, item_id: 101 })] })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.hero.title);
  });

  it("asks captains to report the played map after heroes finish without a veto", async () => {
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      score: { home: 0, away: 0 }
    } as unknown as Encounter);
    mockStates(
      unavailableState("not_configured", { home: true, away: true }),
      readyState({
        session: session({ kind: "hero", status: "completed" }),
        is_complete: true,
        pool: [
          entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by: "home" }),
          entry({ id: 4, item_id: 102, round: 1, status: "banned", picked_by: "away" })
        ]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.mapResult.pickMap);
    expect(document.body.textContent).not.toContain(ROOM.seriesDone.title);
  });

  it("holds the hero phase closed until the map it bans for is known", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: ["ban_home"],
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 1 })]
      }),
      unavailableState("waiting_map", { home: true, away: true })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.waitingMapTitle);
  });
});

describe("return navigation", () => {
  const backArrow = () =>
    document.body.querySelector<HTMLAnchorElement>(`a[aria-label="${ROOM.back}"]`);

  async function renderRoom() {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: ["ban_home"],
        pool: [entry({ id: 1, item_id: 21 })]
      }),
      unavailableState("not_configured", { home: true, away: true })
    );
    await render();
  }

  it("returns to the page the room was opened from", async () => {
    // Mid-tournament the room is opened from the bracket, and that is where the
    // next match is picked — the encounter page is the wrong place to land.
    search = new URLSearchParams({ from: "/tournaments/87/bracket?stage=5" });
    await renderRoom();

    expect(backArrow()?.getAttribute("href")).toBe("/tournaments/87/bracket?stage=5");
  });

  it("falls back to the encounter without a caller to return to", async () => {
    await renderRoom();

    expect(backArrow()?.getAttribute("href")).toBe("/encounters/4242");
  });

  it("refuses an off-site destination", async () => {
    search = new URLSearchParams({ from: "//evil.example.com/phish" });
    await renderRoom();

    expect(backArrow()?.getAttribute("href")).toBe("/encounters/4242");
  });
});

describe("merged header layout", () => {
  it("keeps the room header inside the Map Pool card, with the first-pick note moved into Steps", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: ["ban_home", "ban_away"],
        pool: [entry({ id: 1, item_id: 21 }), entry({ id: 2, item_id: 22 })]
      }),
      readyState({ session: session({ kind: "hero" }) })
    );
    await render();

    const cards = Array.from(document.body.querySelectorAll('[data-ui="card"]'));
    const poolCard = cards.find((card) => card.textContent?.includes(ROOM.map.title));
    const stepsCard = cards.find((card) => card.textContent?.includes(ROOM.steps.title));
    expect(poolCard).toBeTruthy();
    expect(stepsCard).toBeTruthy();
    expect(stepsCard).not.toBe(poolCard);

    // The former standalone header (back/title, team matchup) now lives inside the Map Pool card.
    expect(poolCard?.textContent).toContain(ROOM.title);
    expect(poolCard?.textContent).toContain("Bright Wolves");
    expect(poolCard?.textContent).toContain("Quiet Foxes");

    // "{team} goes first" moved out of the header and into the Steps card.
    const firstBanner = ROOM.firstBanner.replace("{team}", "Bright Wolves");
    expect(stepsCard?.textContent).toContain(firstBanner);
    expect(poolCard?.textContent).not.toContain(firstBanner);
  });
});

describe("Hero Pool tile redesign", () => {
  it("filters icon-only hero tiles by role via the Filters chip group", async () => {
    getAllHeroes.mockResolvedValue({
      results: [
        { id: 101, name: "Ana", slug: "ana", image_path: "", type: "Support", role: "support" },
        {
          id: 102,
          name: "Reinhardt",
          slug: "reinhardt",
          image_path: "",
          type: "Tank",
          role: "tank"
        }
      ]
    });
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_home", "ban_away"],
        pool: [entry({ id: 1, item_id: 101 }), entry({ id: 2, item_id: 102 })]
      })
    );
    await render();

    expect(document.body.querySelector('button[title="Ana"]')).toBeTruthy();
    expect(document.body.querySelector('button[title="Reinhardt"]')).toBeTruthy();

    const filterGroup = document.body.querySelector('[role="group"][aria-label="Filters"]');
    expect(filterGroup).toBeTruthy();
    const tankChip = Array.from(filterGroup!.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Tank")
    );
    expect(tankChip).toBeTruthy();

    await act(async () => {
      tankChip!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(document.body.querySelector('button[title="Reinhardt"]')).toBeTruthy();
    expect(document.body.querySelector('button[title="Ana"]')).toBeFalsy();
  });

  it("crosses out an unavailable hero tile instead of a status badge", async () => {
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        pool: [
          entry({ id: 1, item_id: 101, status: "available" }),
          entry({ id: 2, item_id: 102, status: "banned" })
        ]
      })
    );
    await render();

    const availableTile = document.body.querySelector('button[title="Hero 101"]');
    const bannedTile = document.body.querySelector('button[title="Hero 102"]');
    expect(availableTile?.querySelector("svg.lucide-ban")).toBeFalsy();
    expect(bannedTile?.querySelector("svg.lucide-ban")).toBeTruthy();
    // Icon-only tile: no visible status badge/name text (unlike the old badge
    // footer) -- only the fallback-avatar initials can legitimately show.
    expect(bannedTile?.textContent).not.toContain("Banned");
  });
});

describe("captain actions", () => {
  it("sends a ban for the active phase's kind on confirm", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: ["ban_home"],
        pool: [entry({ id: 1, item_id: 21 })],
        turn_side: "home",
        expected_action: "ban",
        viewer_can_act: true,
        allowed_actions: ["ban"]
      }),
      unavailableState("not_configured")
    );
    performPickBanAction.mockResolvedValue(entry({ id: 1, item_id: 21, status: "banned" }));
    await render();

    const tile = Array.from(container.querySelectorAll("button")).find((b) =>
      b.textContent?.includes("Map 21")
    );
    await act(async () => {
      tile?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    const confirm = Array.from(container.querySelectorAll("button")).find(
      (b) => b.textContent?.includes("Map 21") && b.textContent?.toLowerCase().includes("ban")
    );
    await act(async () => {
      confirm?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    await settle();

    expect(performPickBanAction).toHaveBeenCalledWith("map", 4242, { item_id: 21, action: "ban" });
  });
});

describe("admin controls", () => {
  it("renders the reset/act panel for a workspace admin, with protect offered when the sequence uses it", async () => {
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_home", "protect_away", "pick_home"],
        pool: [entry({ id: 1, item_id: 101 })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.admin.title);
    expect(document.body.textContent).toContain(ROOM.action.protect);
  });

  it("lets an admin elect the round's opener when the losing captain is unreachable", async () => {
    // The only other control on this screen is a session-wiping reset — which
    // re-creates round 1 and walks into the same wall one map later.
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [
          entry({ id: 10, item_id: 21, round: 1, status: "played", action_index: 2 }),
          entry({ id: 11, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({
          kind: "hero",
          status: "completed",
          awaiting_choice: true,
          pending_loser_side: "away"
        }),
        is_complete: true,
        sequence: ["ban_home"],
        pool: [entry({ id: 1, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.admin.electLabel);
    const panel = document.body.textContent ?? "";
    expect(panel).toContain(ROOM.side.home);
    expect(panel).toContain(ROOM.side.away);
  });

  it("omits the reset/act panel for a non-admin captain", async () => {
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        sequence: ["ban_home"],
        pool: [entry({ id: 1, item_id: 101 })]
      })
    );
    await render();

    expect(document.body.textContent).not.toContain(ROOM.admin.title);
  });
});
