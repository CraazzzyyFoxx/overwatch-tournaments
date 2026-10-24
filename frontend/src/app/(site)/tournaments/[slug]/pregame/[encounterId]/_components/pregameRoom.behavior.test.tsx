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
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import type * as OverwatchMatchUI from "@/disciplines/overwatch/match";
import type * as MatchCharactersModule from "@/disciplines/overwatch/match/MatchCharacters";
import { loadMatchUI } from "@/disciplines/registry/match";
import en from "@/i18n/messages/en.json";
import { ApiError } from "@/lib/api/error";
import { notify } from "@/lib/notify";
import { useAuthProfileStore } from "@/stores/auth-profile.store";
import type { Encounter } from "@/types/encounter.types";
import type {
  PickBanEntry,
  PickBanGame,
  PickBanResolvedStep,
  PickBanSession,
  PickBanState,
  PickBanSubmission
} from "@/types/tournament.types";
import { pickedItemsInOrder } from "@/components/pick-ban/pick-ban-model";

import { PregameRoom } from "./PregameRoom";
import { derivePregameLoop } from "./pregameRoom.model";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getPickBanState = vi.fn();
const performPickBanAction = vi.fn();
const undoLastAction = vi.fn();
const submitDraft = vi.fn();
const disputeStep = vi.fn();
const adminPickBanSubmit = vi.fn();
const adminPickBanAct = vi.fn();
const adminPickBanReopen = vi.fn();
const resetPickBanSession = vi.fn();
const adminPickBanPause = vi.fn();
const adminPickBanExtend = vi.fn();
const adminPickBanCancel = vi.fn();
const adminTechnicalLoss = vi.fn();
const getPregameRoomHistory = vi.fn();
const setEncounterReadiness = vi.fn();
const markReady = vi.fn();
const getEncounter = vi.fn();
const getMatch = vi.fn();
const getAllMaps = vi.fn();
const getAllHeroes = vi.fn();
const getMetadata = vi.fn();
const getMyRole = vi.fn();
const getReports = vi.fn();
const submitReport = vi.fn();
const reportGame = vi.fn();
const selectGameMap = vi.fn();
const correctGameResult = vi.fn();
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
    submitDraft: (...args: unknown[]) => submitDraft(...args),
    disputeStep: (...args: unknown[]) => disputeStep(...args),
    electOpener: vi.fn(),
    reportGame: (...args: unknown[]) => reportGame(...args),
    selectGameMap: (...args: unknown[]) => selectGameMap(...args),
    correctGameResult: (...args: unknown[]) => correctGameResult(...args)
  }
}));
vi.mock("@/services/captain.service", () => ({
  default: {
    getMyRole: (...args: unknown[]) => getMyRole(...args),
    getReports: (...args: unknown[]) => getReports(...args),
    submitReport: (...args: unknown[]) => submitReport(...args)
  }
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    resetPickBanSession: (...args: unknown[]) => resetPickBanSession(...args),
    adminPickBanAct: (...args: unknown[]) => adminPickBanAct(...args),
    adminPickBanElectOpener: vi.fn(),
    adminPickBanSubmit: (...args: unknown[]) => adminPickBanSubmit(...args),
    adminPickBanReopen: (...args: unknown[]) => adminPickBanReopen(...args),
    adminPickBanPause: (...args: unknown[]) => adminPickBanPause(...args),
    adminPickBanExtend: (...args: unknown[]) => adminPickBanExtend(...args),
    adminPickBanCancel: (...args: unknown[]) => adminPickBanCancel(...args),
    adminTechnicalLoss: (...args: unknown[]) => adminTechnicalLoss(...args),
    setEncounterReadiness: (...args: unknown[]) => setEncounterReadiness(...args),
    getPregameRoomHistory: (...args: unknown[]) => getPregameRoomHistory(...args)
  }
}));
vi.mock("@/services/encounter.service", () => ({
  default: {
    getEncounter: (...args: unknown[]) => getEncounter(...args),
    getMatch: (...args: unknown[]) => getMatch(...args)
  }
}));
// One native catalog read serves both kinds; the room asks for its encounter's own game.
vi.mock("@/services/catalog.service", () => ({
  default: {
    list: (discipline: string, kind: string, ...rest: unknown[]) =>
      kind === "map" ? getAllMaps(discipline, kind, ...rest) : getAllHeroes(discipline, kind, ...rest)
  }
}));
// The room names its game's module through native metadata; only the declared classes and capabilities matter here.
vi.mock("@/services/discipline.service", () => ({
  default: { list: async () => [], metadata: (...args: unknown[]) => getMetadata(...args) }
}));
// The room now mounts `RoomChat` beside every phase. These cases are about the
// phases, so the viewer is a spectator here (403 -> `null`) and the panel keeps
// to itself; without the mock every case would also fire a real chat request.
vi.mock("@/services/roomChat.service", () => ({
  default: { getEnvelope: vi.fn().mockResolvedValue(null), postMessage: vi.fn() }
}));
vi.mock("@/hooks/useRealtimeTopic", () => ({
  useRealtimeTopic: vi.fn()
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
// A player's previous-map heroes are the game's match module's `matchCharacters` slot. The module and its lazy slot
// are two chunk loads, each a module-runner round trip that settled outside the room's acts. The module is loaded in
// `beforeAll`; the slot is the real renderer without the lazy boundary, so it renders on the widget's first commit.
vi.mock("@/disciplines/overwatch/match", async (importOriginal) => {
  const { default: ui } = await importOriginal<typeof OverwatchMatchUI>();
  const { default: matchCharacters } = await vi.importActual<typeof MatchCharactersModule>(
    "@/disciplines/overwatch/match/MatchCharacters"
  );
  return { default: { ...ui, slots: { ...ui.slots, matchCharacters } } };
});
beforeAll(async () => {
  await loadMatchUI("overwatch");
});

const ROOM = en.pickBan.room;

const MAPS = [21, 22, 23].map((id) => ({ id, name: `Map ${id}`, image_path: "" }));
const HEROES = [101, 102, 103].map((id) => ({
  id,
  name: `Hero ${id}`,
  slug: `hero-${id}`,
  image_path: "",
  attrs: { class: "damage" }
}));

/** Three heroes with two distinct roles: enough to tell a role rule from an item one. */
const HERO_CATALOG = [
  { id: 201, name: "Tank A", attrs: { class: "tank" }, image_path: "" },
  { id: 202, name: "Tank B", attrs: { class: "tank" }, image_path: "" },
  { id: 203, name: "Support A", attrs: { class: "support" }, image_path: "" }
];

// The two participations of the fixture encounter: slot 1 and slot 2.
const HOME = 71;
const AWAY = 72;

/** The encounter's live seats, with a standing each. */
function seats(scoreOne = 0, scoreTwo = 0) {
  return [
    {
      id: HOME,
      slot: 1,
      team_id: 7,
      name: "Bright Wolves",
      seed: 1,
      score: scoreOne,
      placement: null,
      active: true,
      team: { id: 7, name: "Bright Wolves", avg_sr: 3000, captain_id: 1, players: [] }
    },
    {
      id: AWAY,
      slot: 2,
      team_id: 8,
      name: "Quiet Foxes",
      seed: 4,
      score: scoreTwo,
      placement: null,
      active: true,
      team: { id: 8, name: "Quiet Foxes", avg_sr: 3000, captain_id: 2, players: [] }
    }
  ];
}

function encounter(): Encounter {
  return {
    id: 4242,
    slot_count: 2,
    teams: seats(),
    games: [],
    matches: [],
    discipline: "overwatch",
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
    picked_by_kind: null,
    picked_by_team_id: null,
    protected_by_kind: null,
    protected_by_team_id: null,
    status: "available",
    carried_from_round: null,
    ...overrides
  };
}

/** One position of the series, awaiting its result unless told otherwise. */
function game(overrides: Partial<PickBanGame> & { position: number }): PickBanGame {
  return {
    id: 900 + overrides.position,
    map_id: 21,
    state: "awaiting_result",
    result_source: null,
    result_version: 1,
    confirmed_at: null,
    results: [],
    claims: [],
    ...overrides
  };
}

/** One game's numbers on the two seats, slot 1 first. */
function lines(one: number, two: number) {
  return [
    { encounter_team_id: HOME, score: one, placement: null, column_values: {} },
    { encounter_team_id: AWAY, score: two, placement: null, column_values: {} }
  ];
}

/** A confirmed position, the way the server reports one both captains agreed. */
function confirmed(position: number, mapId: number, home: number, away: number): PickBanGame {
  return game({
    position,
    map_id: mapId,
    state: "confirmed",
    result_source: "captain_agreement",
    confirmed_at: "2026-08-01T11:00:00Z",
    results: lines(home, away),
    claims: [
      { claimant_team_id: HOME, basis_version: 1, results: lines(home, away) },
      { claimant_team_id: AWAY, basis_version: 1, results: lines(home, away) }
    ]
  });
}

function session(overrides: Partial<PickBanSession> = {}): PickBanSession {
  return {
    id: 1,
    kind: "map",
    status: "active",
    first_team_id: HOME,
    awaiting_choice: false,
    pending_chooser_team_id: null,
    seed_source: "bracket_slot",
    slot_reserves: null,
    started_at: "2026-08-01T10:00:00Z",
    current_step_started_at: null,
    paused_at: null,
    ...overrides
  };
}

/** One resolved step of a v2 session: an open single-item ban by home unless told otherwise. */
function step(overrides: Partial<PickBanResolvedStep> & { index: number }): PickBanResolvedStep {
  return {
    round: 1,
    phase_id: "main",
    step_id: `s${overrides.index}`,
    action: "ban",
    actors: [HOME],
    actors_token: null,
    count: 1,
    min: 1,
    blind: false,
    target: null,
    lifetime: 1,
    timer_seconds: null,
    on_timeout: "random_fill",
    dispute: { enabled: false, max: 0 },
    eligible: {},
    constraints: [],
    ...overrides
  };
}

function submission(
  overrides: Partial<PickBanSubmission> & { step_index: number; encounter_team_id: number }
): PickBanSubmission {
  return { attempt: 1, state: "revealed", items: [], ...overrides };
}

/**
 * A run of finished one-item steps: the sequence AND the submissions behind it.
 *
 * Both, because the board and the per-side lists are two different reads now —
 * entries say what is banned, submissions say who spent it (and a duplicate
 * merges into one entry while staying on both sides' submissions).
 */
function acts(
  specs: {
    side: "home" | "away"; // which seat of the fixture
    itemId: number;
    action?: "ban" | "protect";
    round?: number | null;
  }[]
): { sequence: PickBanResolvedStep[]; submissions: PickBanSubmission[] } {
  return {
    sequence: specs.map((spec, index) =>
      step({
        index,
        round: spec.round === undefined ? 1 : spec.round,
        action: spec.action ?? "ban",
        actors: [spec.side === "home" ? HOME : AWAY]
      })
    ),
    submissions: specs.map((spec, index) =>
      submission({
        step_index: index,
        encounter_team_id: spec.side === "home" ? HOME : AWAY,
        items: [{ item_id: spec.itemId, target_player_id: null }]
      })
    )
  };
}

/**
 * The 2026-10-03 shape: one simultaneous blind step both captains fill at
 * once, over a round-1 pool of the three catalog heroes.
 */
function blindRound(
  overrides: Partial<PickBanResolvedStep> = {}
): Pick<
  PickBanState,
  "sequence" | "current_step" | "current_step_index" | "acting_team_ids" | "current_round" | "pool"
> {
  const blind = step({
    index: 0,
    actors: [HOME, AWAY],
    count: 2,
    min: 2,
    blind: true,
    ...overrides
  });
  return {
    sequence: [blind],
    current_step: blind,
    current_step_index: 0,
    acting_team_ids: [HOME, AWAY],
    current_round: 1,
    pool: HERO_CATALOG.map((hero, index) =>
      entry({ id: 30 + index, item_id: hero.id, round: 1 })
    )
  };
}

function readyState(overrides: Partial<PickBanState>): PickBanState {
  return {
    session: session(),
    readiness: { [HOME]: true, [AWAY]: true },
    sequence: [],
    pool: [],
    submissions: [],
    viewer_team_id: HOME,
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: 0,
    current_step: null,
    expected_action: null,
    acting_team_ids: [],
    step_progress: null,
    step_deadline: null,
    current_round: null,
    is_complete: false,
    eligible: null,
    draft_issues: [],
    targets: null,
    sides: [],
    dispute: { available: false, step_index: null, attempts_used: 0, max: 0 },
    undo: { requested_by_team_id: null, step_index: null, item_ids: [], action: null, encounter_team_id: null },
    ...overrides
  };
}

function unavailableState(
  reason: NonNullable<PickBanState["reason"]>,
  readiness: Record<string, boolean> = { [HOME]: false, [AWAY]: false }
): PickBanState {
  return {
    session: null,
    reason,
    readiness,
    sequence: [],
    pool: [],
    submissions: [],
    viewer_team_id: null,
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: null,
    current_step: null,
    expected_action: null,
    acting_team_ids: [],
    step_progress: null,
    step_deadline: null,
    current_round: null,
    is_complete: false,
    eligible: null,
    draft_issues: [],
    targets: null,
    sides: [],
    dispute: { available: false, step_index: null, attempts_used: 0, max: 0 },
    undo: { requested_by_team_id: null, step_index: null, item_ids: [], action: null, encounter_team_id: null }
  };
}

let container: HTMLDivElement;
let root: Root;
let scrollIntoView: Mock;
/** The room's query client, so a case can make the server's next answer land without waiting for a poll. */
let roomClient: QueryClient;

beforeEach(() => {
  vi.clearAllMocks();
  getAllMaps.mockResolvedValue({ results: MAPS });
  getAllHeroes.mockResolvedValue({ results: HEROES });
  getEncounter.mockResolvedValue(encounter());
  getMetadata.mockImplementation(async (_axis: unknown, code: string) => ({
    discipline: { code, character_classes: ["tank", "damage", "support"], capabilities: {} },
    dimensions: [],
    roles: []
  }));
  getMyRole.mockResolvedValue({ encounter_team_id: null, slot: null });
  // The viewer is signed in unless a case says otherwise: only an account is asked for its seat.
  useAuthProfileStore.setState({ status: "authenticated" });
  getReports.mockResolvedValue({ reports: [], form: undefined });
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

/** The Overwatch bans board is a module slot — a lazy chunk — so wait for it to mount. */
async function untilBans() {
  for (let tries = 0; tries < 100 && !document.body.querySelector("[data-hero-bans]"); tries += 1) {
    await settle(1);
  }
}

/** Past the blind draft's ~300ms autosave debounce, then let the response land. */
async function debounce() {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  });
  await settle();
}

async function render(props: { seriesReport?: boolean } = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  roomClient = client;
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

async function showAdminUi() {
  const toggle = Array.from(document.body.querySelectorAll("button")).find(
    (button) => button.textContent?.trim() === ROOM.admin.showUi
  );
  await act(async () => toggle!.click());
  await settle();
}

/**
 * Routes `getPickBanState(kind, id)` mock calls to per-kind canned responses.
 *
 * The server opens one game per picked position, so a map state that says
 * nothing about results gets that default rather than restating it in every
 * fixture; a case about a result passes its own `games`.
 */
function mockStates(map: PickBanState, hero: PickBanState) {
  const mapState: PickBanState =
    map.games != null
      ? map
      : {
          ...map,
          games: pickedItemsInOrder(map.pool).map((entry, index) =>
            game({ position: index + 1, map_id: entry.item_id })
          )
        };
  getPickBanState.mockImplementation((kind: string) =>
    Promise.resolve(kind === "map" ? mapState : hero)
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
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      unavailableState("not_ready", { [HOME]: false, [AWAY]: true }),
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
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      unavailableState("not_ready", { [HOME]: true, [AWAY]: false }),
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
    getMyRole.mockResolvedValue({ encounter_team_id: null, slot: null });
    mockStates(unavailableState("not_ready"), unavailableState("not_configured"));
    await render();

    const button = Array.from(document.body.querySelectorAll("button")).find(
      (b) => b.textContent?.trim() === ROOM.ready.button
    );
    expect(button).toBeUndefined();
  });

  it("asks an anonymous spectator for no seat: only an account can captain", async () => {
    useAuthProfileStore.setState({ status: "anonymous" });
    mockStates(unavailableState("not_ready"), unavailableState("not_configured"));
    await render();

    expect(document.body.textContent).toContain(ROOM.notReadyTitle);
    expect(getMyRole).not.toHaveBeenCalled();
  });

  it("renders the real room behind the gate — matchup and per-side state, no skeletons", async () => {
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      unavailableState("not_ready", { [HOME]: true, [AWAY]: false }),
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

  it("reads the maps and characters of the encounter's own game, never a default one", async () => {
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(unavailableState("not_ready", { [HOME]: true, [AWAY]: false }), unavailableState("not_configured"));
    await render();

    expect(getAllMaps).toHaveBeenCalled();
    expect(getAllHeroes).toHaveBeenCalled();
    for (const call of [...getAllMaps.mock.calls, ...getAllHeroes.mock.calls]) expect(call[0]).toBe("overwatch");
    expect(getAllMaps.mock.calls[0][1]).toBe("map");
    expect(getAllHeroes.mock.calls[0][1]).toBe("character");
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
  it.each([
    { bestOf: 2, home: 1, away: 0, phase: "report" },
    { bestOf: 2, home: 1, away: 1, phase: "done" },
    { bestOf: 3, home: 1, away: 1, phase: "report" }
  ])(
    "routes BO$bestOf $home:$away to $phase without a series summary",
    ({ bestOf, home, away, phase }) => {
      const loop = derivePregameLoop(
        { ...encounter(), best_of: bestOf, teams: seats(home, away) },
        unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
        readyState({
          session: session({ kind: "hero", status: "completed" }),
          is_complete: true,
          pool: [entry({ item_id: 101, round: 2, status: "banned" })]
        })
      );

      expect(loop.phase).toBe(phase);
    }
  );

  it("renders the map phase first when both kinds are configured", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: [step({ index: 0 }), step({ index: 1, actors: [AWAY] })],
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
        sequence: [step({ index: 0 })],
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
    getMyRole.mockResolvedValue({ encounter_team_id: AWAY, slot: 2 });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: [step({ index: 0 }), step({ index: 1, actors: [AWAY] })],
        viewer_team_id: AWAY,
        pool: [
          entry({
            id: 3,
            item_id: 101,
            round: 1,
            status: "banned",
            picked_by_kind: "team", picked_by_team_id: HOME,
            action_index: 0
          }),
          entry({ id: 4, item_id: 102, round: 1 })
        ],
        undo: { requested_by_team_id: null, step_index: 0, item_ids: [101], action: "ban", encounter_team_id: HOME }
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

  it("greys what the step's own rules leave out of `eligible`", async () => {
    // v2 rules are arbitrary condition trees (class must match the target
    // player's role, not banned by this side earlier in the series, one per
    // role...), so the room does not re-derive them: the server names what may
    // be chosen and everything else is inert instead of a 400 after a click.
    getAllHeroes.mockResolvedValue({
      results: [
        { id: 201, name: "Tank A", attrs: { class: "tank" }, image_path: "" },
        { id: 203, name: "Support A", attrs: { class: "support" }, image_path: "" }
      ]
    });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: [step({ index: 0 })],
        current_step: step({ index: 0 }),
        current_step_index: 0,
        acting_team_ids: [HOME],
        viewer_team_id: HOME,
        viewer_can_act: true,
        allowed_actions: ["ban"],
        expected_action: "ban",
        current_round: 1,
        eligible: { item_ids: [203], by_target: null },
        pool: [entry({ id: 3, item_id: 201, round: 1 }), entry({ id: 4, item_id: 203, round: 1 })]
      })
    );
    await render();

    const tile = (name: string) =>
      document.body.querySelector<HTMLButtonElement>(`button[aria-label^="${name}"]`);
    expect(tile("Tank A")?.disabled).toBe(true);
    expect(tile("Tank A")?.className).toContain("grayscale");
    expect(tile("Tank A")?.title).toBe(ROOM.rule.ineligible);
    expect(tile("Support A")?.disabled).toBe(false);
    expect(tile("Support A")?.className).not.toContain("grayscale");
  });

  it("shows the opponent's blind progress as a count, never as items", async () => {
    // A blind step is the one place privacy is the rule: the server never
    // serializes the other side's unrevealed draft, and the room must not
    // invent a stand-in for it either. A filled count is all there is.
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      readyState({
        session: session({ kind: "hero" }),
        ...blindRound(),
        viewer_team_id: HOME,
        viewer_can_act: true,
        allowed_actions: ["ban"],
        step_progress: { [HOME]: { locked: false, filled: 1 }, [AWAY]: { locked: false, filled: 2 } },
        submissions: [
          submission({
            step_index: 0,
            encounter_team_id: HOME,
            state: "draft",
            items: [{ item_id: 201, target_player_id: null }]
          })
        ]
      })
    );
    await render();

    const tray = document.body.querySelector<HTMLElement>("[data-pick-ban-draft]");
    expect(tray).toBeTruthy();
    // The viewer's own pick is spelled out...
    expect(tray?.querySelector('[data-draft-item="201"]')).toBeTruthy();
    // ...the opponent's is a number, and their heroes are nowhere on screen.
    expect(document.body.textContent).toContain("Quiet Foxes: 2/2");
    expect(tray?.textContent).not.toContain("Tank B");
    expect(tray?.textContent).not.toContain("Support A");
  });

  it("refuses the lock while the server still has an objection to the draft", async () => {
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      readyState({
        session: session({ kind: "hero" }),
        ...blindRound(),
        viewer_team_id: HOME,
        viewer_can_act: true,
        allowed_actions: ["ban"],
        draft_issues: ["one hero per opponent player"],
        submissions: [
          submission({
            step_index: 0,
            encounter_team_id: HOME,
            state: "draft",
            items: [
              { item_id: 201, target_player_id: null },
              { item_id: 202, target_player_id: null }
            ]
          })
        ]
      })
    );
    await render();

    const lock = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.draft.lock)
    );
    expect(lock?.disabled).toBe(true);
    // And the reason is on screen, rather than waiting behind a rejected click.
    expect(document.body.querySelector("[data-draft-issues]")?.textContent).toContain(
      "one hero per opponent player"
    );
  });

  it.each([
    { hasLog: true, hasGames: true },
    { hasLog: true, hasGames: false },
    { hasLog: false, hasGames: true },
    { hasLog: false, hasGames: false }
  ])("shows only the previous map's heroes (log: $hasLog, positions: $hasGames)", async ({ hasLog, hasGames }) => {
    const loggedHeroes = HERO_CATALOG.map((hero) => ({ ...hero, image_path: `https://example.test/${hero.id}.png` }));
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 5,
      games: hasGames ? [game({ position: 1, map_id: 21 }), game({ position: 2, map_id: 22 })] : [],
      // Stats matches are logs; official results and replay codes belong to games.
      matches: [
        { id: 501, map_id: 21, map_index: 1, participants: [] },
        { id: 504, map_id: 23, map_index: 3, participants: [] },
        ...(hasLog ? [{ id: 502, map_id: 22, map_index: 2, participants: [] }] : [])
      ]
    });
    // Registrations 57 and 55 are the global players 57 and 55 through their seats' source-team rosters; the
    // observed members played the characters (above a minute) in the segments listed.
    getMatch.mockImplementation(async (id: number) => {
      const played = (team: number, member: number, segments: [number, number][]) =>
        segments.map(([segment, hero]) => ({
          encounter_team_id: team,
          workspace_member_id: member,
          entity_id: loggedHeroes[hero].id,
          segment,
          stat_code: "hero_time_played",
          value: 120
        }));
      return {
        id,
        workspace_id: 1,
        discipline: "overwatch",
        encounter: {
          teams: [
            { id: HOME, team: { players: [{ id: 57, user_id: 57 }] } },
            { id: AWAY, team: { players: [{ id: 55, user_id: 55 }] } }
          ]
        },
        statistics: {
          members: [
            { encounter_team_id: HOME, workspace_member_id: 570, player_id: 57, handle_snapshot: "Home", observed_role: null },
            { encounter_team_id: AWAY, workspace_member_id: 550, player_id: 55, handle_snapshot: "Away", observed_role: null }
          ],
          segments: [],
          entities: loggedHeroes,
          facts: [
            ...played(HOME, 570, [[0, 2]]),
            ...played(AWAY, 550, id === 502 ? [[0, 0], [1, 0], [1, 1]] : [[0, 2]])
          ]
        }
      };
    });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      readyState({
        session: session({ kind: "hero" }),
        ...blindRound({ target: "opponent_player", round: 3 }),
        current_round: 3,
        viewer_team_id: HOME,
        viewer_can_act: true,
        allowed_actions: ["ban"],
        eligible: { item_ids: [201, 202], by_target: { "55": [201, 202] } },
        targets: {
          [HOME]: [],
          [AWAY]: [{ player_id: 55, name: "Foxy", role: { dimension: "player_role", role: "tank" }, is_substitution: false, division: 7 }]
        }
      })
    );
    await render();
    const row = document.body.querySelector('[data-target-player="55"]')!.closest("li")!;
    if (hasLog) {
      expect(Array.from(row.querySelectorAll("ul img")).map((image) => image.getAttribute("alt"))).toEqual(["Tank A", "Tank B"]);
    } else {
      expect(row.textContent).toContain(ROOM.playerHeroes.noLog);
      expect(row.querySelector("ul")).toBeNull();
    }
  });

  it("bans for the opponent player the captain chose, and says so on the wire", async () => {
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    submitDraft.mockResolvedValue(readyState({ session: session({ kind: "hero" }) }));
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      readyState({
        session: session({ kind: "hero" }),
        ...blindRound({ target: "opponent_player" }),
        viewer_team_id: HOME,
        viewer_can_act: true,
        allowed_actions: ["ban"],
        eligible: { item_ids: [201, 202], by_target: { "55": [201], "56": [202] } },
        targets: {
          [HOME]: [],
          [AWAY]: [
            {
              player_id: 55,
              name: "Foxy",
              role: { dimension: "player_role", role: "tank" },
              is_substitution: false,
              division: 7
            },
            {
              player_id: 56,
              name: "Vixen",
              role: { dimension: "player_role", role: "tank" },
              is_substitution: true,
              division: 12
            }
          ]
        }
      })
    );
    await render();

    // The hero is not the whole choice: WHO it is banned for comes first, and
    // it narrows which heroes are legal at all.
    const row = document.body.querySelector<HTMLButtonElement>('[data-target-player="56"]');
    expect(row).toBeTruthy();
    await act(async () => row!.click());
    await settle();

    // 201 is Foxy's hero, not Vixen's: with Vixen selected it is inert.
    const tile = (name: string) =>
      document.body.querySelector<HTMLButtonElement>(`button[aria-label^="${name}"]`);
    expect(tile("Tank A")?.disabled).toBe(true);

    await act(async () => tile("Tank B")!.click());
    await debounce();

    expect(submitDraft).toHaveBeenCalledWith("hero", 4242, {
      items: [{ item_id: 202, target_player_id: 56 }],
      lock: false
    });
  });

  it("says why and still locks when the opponent has no roster to ban for", async () => {
    // No roster means no target and no eligible hero. The server caps `min` by
    // what is choosable (so `draft_issues` is empty) — a room that re-checked
    // the step's raw `min` would hold a Lock the server accepts disabled forever.
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    submitDraft.mockResolvedValue(readyState({ session: session({ kind: "hero" }) }));
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      readyState({
        session: session({ kind: "hero" }),
        ...blindRound({ target: "opponent_player", count: 5, min: 5 }),
        viewer_team_id: HOME,
        viewer_can_act: true,
        allowed_actions: ["ban"],
        eligible: { item_ids: [], by_target: {} },
        draft_issues: [],
        targets: { [HOME]: [], [AWAY]: [] }
      })
    );
    await render();

    expect(document.body.querySelector("[data-pick-ban-no-roster]")?.textContent).toContain(
      ROOM.target.noRoster.replace("{team}", "Quiet Foxes")
    );
    const lock = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.draft.lock)
    );
    expect(lock?.disabled).toBe(false);

    await act(async () => lock!.click());
    await settle();

    expect(submitDraft).toHaveBeenCalledWith("hero", 4242, { items: [], lock: true });
  });

  it("marks the heroes both sides banned once the blind step reveals", async () => {
    // Duplicates merge into ONE banned entry, so without the mark a captain
    // reads the board and finds a ban they paid for missing from their column.
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      readyState({
        session: session({ kind: "hero" }),
        sequence: [
          step({ index: 0, actors: [HOME, AWAY], count: 2, min: 2, blind: true }),
          step({ index: 1 })
        ],
        current_step_index: 1,
        current_step: step({ index: 1 }),
        current_round: 1,
        submissions: [
          submission({
            step_index: 0,
            encounter_team_id: HOME,
            items: [
              { item_id: 201, target_player_id: null },
              { item_id: 202, target_player_id: null }
            ]
          }),
          submission({
            step_index: 0,
            encounter_team_id: AWAY,
            items: [
              { item_id: 202, target_player_id: null },
              { item_id: 203, target_player_id: null }
            ]
          })
        ],
        pool: [
          entry({ id: 3, item_id: 201, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME }),
          entry({ id: 4, item_id: 202, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME }),
          entry({ id: 5, item_id: 203, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: AWAY })
        ]
      })
    );
    await render();

    const reveal = document.body.querySelector<HTMLElement>("[data-pick-ban-reveal]");
    expect(reveal).toBeTruthy();
    const sides = Array.from(reveal!.querySelectorAll<HTMLElement>("[data-reveal-team]"));
    expect(sides.map((side) => side.dataset.revealTeam)).toEqual([String(HOME), String(AWAY)]);
    // Tank B is on both columns and marked on both; the rest are not.
    expect(reveal!.querySelectorAll('[data-reveal-item="202"][data-matched="true"]')).toHaveLength(2);
    expect(reveal!.querySelector('[data-reveal-item="201"]')?.dataset.matched).toBeUndefined();
    expect(reveal!.textContent).toContain(ROOM.reveal.matched);
  });

  /** A revealed blind step with one more step still to come, so the room stays on the board. */
  function revealedBlind(dispute: PickBanState["dispute"]): PickBanState {
    return readyState({
      session: session({ kind: "hero" }),
      sequence: [
        step({ index: 0, actors: [HOME, AWAY], count: 1, min: 1, blind: true }),
        step({ index: 1 })
      ],
      current_step_index: 1,
      current_step: step({ index: 1 }),
      current_round: 1,
      viewer_team_id: HOME,
      dispute,
      submissions: [
        submission({ step_index: 0, encounter_team_id: HOME, items: [{ item_id: 201, target_player_id: null }] }),
        submission({ step_index: 0, encounter_team_id: AWAY, items: [{ item_id: 203, target_player_id: null }] })
      ],
      pool: [entry({ id: 3, item_id: 201, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME })]
    });
  }

  const DISPUTE_LABEL = ROOM.dispute.button.replace("{used}", "0").replace("{max}", "1");

  it("offers the redo when the server says this viewer may ask for it", async () => {
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    disputeStep.mockResolvedValue(readyState({ session: session({ kind: "hero" }) }));
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      revealedBlind({ available: true, step_index: 0, attempts_used: 0, max: 1 })
    );
    await render();

    const redo = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(DISPUTE_LABEL)
    );
    expect(redo).toBeTruthy();
  });

  it("withholds the redo from a viewer who has spent their attempts", async () => {
    // `available` is the server's whole answer — enabled, attempts left, and
    // nothing played on top of the step. The room never second-guesses it.
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      revealedBlind({ available: false, step_index: 0, attempts_used: 1, max: 1 })
    );
    await render();

    expect(document.body.querySelector("[data-pick-ban-reveal]")).toBeTruthy();
    expect(document.body.textContent).not.toContain(DISPUTE_LABEL);
  });

  it("charts the series' play order once, in the header", async () => {
    // The pool card used to repeat the whole play order under the grid — the
    // same maps the header's series filmstrip already charts, twice on one
    // screen. These two are the only ordered lists the room draws.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        viewer_team_id: HOME,
        sequence: [step({ index: 0 }), step({ index: 1, actors: [AWAY] }), step({ index: 2, action: "decider", actors: [null] })],
        current_round: 2,
        games: [confirmed(1, 21, 2, 1)],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2 }),
          entry({ id: 3, item_id: 23, round: 2 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: [step({ index: 0 })],
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
        { id: 201, name: "Tank A", attrs: { class: "tank" }, image_path: "" },
        { id: 202, name: "Tank B", attrs: { class: "tank" }, image_path: "" }
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
        sequence: [step({ index: 0, action: "protect" }), step({ index: 1, actors: [AWAY] })],
        current_round: 1,
        pool: [
          entry({
            id: 3,
            item_id: 201,
            round: 1,
            status: "protected",
            protected_by_kind: "team", protected_by_team_id: HOME,
            action_index: 0
          }),
          entry({
            id: 4,
            item_id: 202,
            round: 1,
            status: "banned",
            picked_by_kind: "team", picked_by_team_id: AWAY,
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
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: [step({ index: 0 })],
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
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        ...acts([
          { side: "home", itemId: 101 },
          { side: "away", itemId: 102 },
          { side: "away", itemId: 103, action: "protect" },
          { side: "home", itemId: 104, round: 2 }
        ]),
        pool: [
          entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME }),
          entry({ id: 4, item_id: 102, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: AWAY }),
          entry({ id: 5, item_id: 103, round: 1, status: "protected", protected_by_kind: "team", protected_by_team_id: AWAY }),
          // Another round's ban: the lobby for THIS map must not carry it.
          entry({ id: 6, item_id: 104, round: 2, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME })
        ]
      })
    );
    await render();
    await untilBans();

    expect(document.body.textContent).toContain(ROOM.heroBans.eyebrow);
    const sides = Array.from(document.body.querySelectorAll<HTMLElement>("[data-hero-bans]"));
    expect(sides.map((tile) => tile.dataset.heroBans)).toEqual(["1", "2"]);
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

  it("badges a carried ban with the map it came from, and copies the lobby list", async () => {
    // A 2-map ban spent on map 1 is still in force on map 2, but nobody acted
    // on it here — so it is not a ban of this round, it is a leftover with an
    // origin. And the list the captains actually need is the flat one they
    // tick off in the custom game, grouped the way that hero list is.
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    const writeText = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true
    });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        games: [confirmed(1, 21, 2, 1), game({ position: 2, map_id: 22 })],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: HOME,
        ...acts([{ side: "away", itemId: 202, round: 2 }]),
        pool: [
          entry({
            id: 3,
            item_id: 201,
            round: 2,
            status: "banned",
            picked_by_kind: "team", picked_by_team_id: HOME,
            carried_from_round: 1
          }),
          entry({ id: 4, item_id: 202, round: 2, status: "banned", picked_by_kind: "team", picked_by_team_id: AWAY }),
          entry({ id: 5, item_id: 203, round: 2, status: "available" })
        ]
      })
    );
    await render();
    await untilBans();

    // The carried ban sits in the column of the side that spent it, wearing
    // the map it was spent on rather than passing as this round's work.
    const sides = Array.from(document.body.querySelectorAll<HTMLElement>("[data-hero-bans]"));
    expect(sides[0].textContent).toContain("Tank A");
    expect(sides[0].querySelector('[data-carried-from="1"]')).toBeTruthy();
    expect(sides[1].querySelector("[data-carried-from]")).toBeNull();

    // The lobby needs the final bans, carried ones included — and only them:
    // what is still playable is not the list anyone transfers.
    const unavailable = document.body.querySelector<HTMLElement>("[data-hero-unavailable]");
    expect(unavailable?.textContent).toContain(ROOM.heroBans.unavailableOn.replace("{n}", "2"));
    expect(
      Array.from(unavailable!.querySelectorAll<HTMLElement>("[data-hero-banned]")).map(
        (row) => row.dataset.heroBanned
      )
    ).toEqual(["201", "202"]);
    expect(unavailable?.textContent).not.toContain("Support A");

    const copy = Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === ROOM.heroBans.copy
    );
    await act(async () => copy!.click());
    await settle();

    expect(writeText).toHaveBeenCalledWith("Tank: Tank A, Tank B");
  });

  it("leaves the result screen without a bans block when no heroes were banned", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.mapResult.report);
    expect(document.body.textContent).not.toContain(ROOM.heroBans.eyebrow);
    expect(document.body.querySelector("[data-hero-bans]")).toBeNull();
  });

  it("renders League's own bans board on the result screen, never Overwatch's", async () => {
    getEncounter.mockResolvedValue({ ...encounter(), discipline: "lol" } as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        ...acts([{ side: "home", itemId: 101 }]),
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME })]
      })
    );
    await render();
    for (let tries = 0; tries < 100 && !document.body.querySelector("[data-character-bans]"); tries += 1) {
      await settle(1);
    }

    expect(document.body.textContent).toContain(ROOM.mapResult.report);
    expect(document.body.querySelector('[data-character-bans="1"]')?.textContent).toContain("Hero 101");
    expect(document.body.textContent).toContain(ROOM.characterBans.eyebrow);
    // The Overwatch board and its lobby copy stay out; nothing claims an error.
    expect(document.body.querySelector("[data-hero-bans]")).toBeNull();
    expect(document.body.textContent).not.toContain(ROOM.heroBans.copy);
    expect(document.body.querySelector('[role="alert"]')).toBeNull();
  });

  it("offers the hero undo under the bans, and asks the opponent to agree", async () => {
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: HOME,
        ...acts([{ side: "home", itemId: 101 }]),
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME })],
        undo: { requested_by_team_id: null, step_index: 0, item_ids: [101], action: "ban", encounter_team_id: HOME }
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
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: HOME,
        ...acts([{ side: "away", itemId: 101 }]),
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: AWAY })],
        undo: { requested_by_team_id: AWAY, step_index: 0, item_ids: [101], action: "ban", encounter_team_id: AWAY }
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
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: HOME,
        ...acts([{ side: "home", itemId: 101 }]),
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME })],
        undo: { requested_by_team_id: HOME, step_index: 0, item_ids: [101], action: "ban", encounter_team_id: HOME }
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
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: HOME,
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME })],
        undo: { requested_by_team_id: null, step_index: null, item_ids: [], action: null, encounter_team_id: null }
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
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })],
        games: [
          game({
            position: 1,
            map_id: 21,
            claims: [{ claimant_team_id: HOME, basis_version: 1, results: lines(3, 1) }]
          })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: [step({ index: 0 })],
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

  it("files the captain's claim against the position's game, not against the map", async () => {
    // The map is not the identity of a result: a series can play the same map
    // twice, and the claim belongs to the position the room is on.
    reportGame.mockResolvedValue({
      disputed: false,
      resolved: false,
      game: game({ position: 1, map_id: 21, id: 77 })
    });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        games: [game({ position: 1, map_id: 21, id: 77 })],
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    const byText = (label: string) =>
      Array.from(document.body.querySelectorAll("button")).find(
        (button) => button.textContent?.trim() === label
      );
    await act(async () => byText(ROOM.mapResult.report)!.click());
    await settle();

    const submit = byText(ROOM.mapReport.submit);
    expect(submit).toBeTruthy();
    await act(async () => submit!.click());
    await settle();

    expect(reportGame).toHaveBeenCalledWith(4242, 77, {
      basis_version: 1,
      results: [
        { encounter_team_id: HOME, score: 0 },
        { encounter_team_id: AWAY, score: 0 }
      ]
    });
  });

  it("charts every settled map of the series with its accepted score", async () => {
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      teams: seats(1, 0)
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        games: [confirmed(1, 21, 3, 1), game({ position: 2, map_id: 22 })],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: [step({ index: 0 })],
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
      teams: seats(0, 0),
      matches: [
        { map_id: 21, map_index: 1, score: { home: 1, away: 0 } },
        { map_id: 23, map_index: 3, score: { home: 0, away: 0 } }
      ]
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
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
        sequence: [step({ index: 0 })],
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
    // from whichever row happened to come first. The POSITION keys a game.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      teams: seats(1, 1),
      matches: []
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        games: [confirmed(1, 21, 2, 1), confirmed(2, 21, 0, 2), game({ position: 3, map_id: 21 })],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 21, round: 2, status: "picked", action_index: 5 }),
          entry({ id: 3, item_id: 21, round: 3, status: "picked", action_index: 8 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: [step({ index: 0 })],
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

  it("stays on the hero phase while the hero round for the pending map is still catching up", async () => {
    // Map 2 was just picked; the hero session still only holds round 1, whose
    // steps are all taken. Jumping to "report" here would skip map 2's bans.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        games: [confirmed(1, 21, 2, 1), game({ position: 2, map_id: 22 })],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        sequence: [step({ index: 0 })],
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
    getMyRole.mockResolvedValue({ encounter_team_id: null, slot: null });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: null,
        games: [confirmed(1, 21, 2, 1), game({ position: 2, map_id: 22 })],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({
          kind: "hero",
          status: "completed",
          awaiting_choice: true,
          pending_chooser_team_id: AWAY
        }),
        is_complete: true,
        viewer_team_id: null,
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(
      ROOM.electOpener.waiting.replace("{team}", "Quiet Foxes")
    );
  });

  /** A series with every position picked, banned, played and confirmed. */
  function settledSeries(viewerSide: "home" | "away" | null) {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: viewerSide === "home" ? HOME : viewerSide === "away" ? AWAY : null,
        games: [confirmed(1, 21, 2, 1)],
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: viewerSide === "home" ? HOME : viewerSide === "away" ? AWAY : null,
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
  }

  async function renderFinalReport(resultStatus: "none" | "confirmed") {
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 1,
      result_status: resultStatus,
      teams: seats(1, 0)
    } as unknown as Encounter);
    settledSeries("home");
    await render();
  }

  const scoreInput = (label: string) =>
    document.body.querySelector<HTMLInputElement>(`input[aria-label="Score for ${label}"]`);

  it("offers the final report, prefilled with the score the room collected", async () => {
    // The room used to end on a "nothing left to decide" notice and send
    // captains off to hunt for the report dialog elsewhere. The form belongs
    // here, prefilled with the score the room itself just collected map by map.
    await renderFinalReport("none");

    expect(document.body.textContent).toContain(ROOM.finalReport.title);
    // Prefilled from the encounter's own series score, not left at 0:0.
    expect(scoreInput("Bright Wolves")?.value).toBe("1");
    expect(scoreInput("Quiet Foxes")?.value).toBe("0");
    expect(document.body.textContent).toContain(en.matchReport.submit);
  });

  it("offers the final report of a series the maps confirmed, its score read-only", async () => {
    await renderFinalReport("confirmed");

    expect(document.body.textContent).toContain(ROOM.finalReport.title);
    expect(scoreInput("Bright Wolves")).toBeNull();
    expect(document.body.textContent).toContain(en.matchReport.confirmedReportHint);
    expect(document.body.textContent).toContain(en.matchReport.submit);
  });

  it("closes with nothing but the header for anyone who captains neither side", async () => {
    // A spectator, or an admin who is not a captain, has no report to file: the
    // captain report is per-team. Nothing is rendered in its place — the header
    // already carries the score, the completed mark and the way back.
    settledSeries(null);
    await render();

    expect(document.body.textContent).not.toContain(ROOM.finalReport.title);
    expect(document.body.querySelector('input[aria-label="Score for Bright Wolves"]')).toBeNull();
  });

  it("never asks a scrim captain for a series report", async () => {
    // A scrim publishes no result, and the report form is built from a
    // per-tournament config the scrims container does not have — so a captain who
    // WOULD be asked in a tournament is asked for nothing at all.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 1,
      teams: seats(1, 0)
    } as unknown as Encounter);
    settledSeries("home");
    await render({ seriesReport: false });

    expect(document.body.textContent).not.toContain(ROOM.finalReport.title);
    // The form itself is gone, not merely hidden behind a heading.
    expect(document.body.textContent).not.toContain(en.matchReport.submit);
    expect(document.body.querySelector('input[aria-label="Score for Bright Wolves"]')).toBeNull();
  });

  it("replays every map's hero bans on the closing screen", async () => {
    // The closing screen used to be the one place in the loop that named
    // nothing about the heroes: `heroActions` keys off the PENDING map, and by
    // the time the series is done there is none, so the record of what each map
    // was played under vanished with the last grid that closed.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      teams: seats(2, 0)
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: null,
        games: [confirmed(1, 21, 2, 1), confirmed(2, 22, 2, 0)],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: null,
        ...acts([
          { side: "home", itemId: 101 },
          { side: "away", itemId: 102, round: 2 }
        ]),
        pool: [
          entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME }),
          entry({ id: 4, item_id: 102, round: 2, status: "banned", picked_by_kind: "team", picked_by_team_id: AWAY })
        ]
      })
    );
    await render();
    await untilBans();

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

  describe("the game's metadata, which its bans slot needs", () => {
    const OW_METADATA = {
      discipline: { code: "overwatch", character_classes: ["tank", "damage", "support"], capabilities: {} },
      dimensions: [],
      roles: []
    };
    const bansBy = (side: "home" | "away") => ({
      pool: [
        entry({
          id: 3,
          item_id: 101,
          round: 1,
          status: "banned",
          picked_by_kind: "team",
          picked_by_team_id: side === "home" ? HOME : AWAY
        })
      ]
    });
    /** The map-result screen: one map picked, its hero bans committed. */
    function mapResultScreen() {
      getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
      mockStates(
        readyState({
          session: session({ kind: "map" }),
          is_complete: true,
          viewer_team_id: HOME,
          pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
        }),
        readyState({
          session: session({ kind: "hero" }),
          is_complete: true,
          viewer_team_id: HOME,
          ...acts([{ side: "home", itemId: 101 }]),
          ...bansBy("home")
        })
      );
    }
    /** The closing screen: the series is done, its bans are the record. */
    function closingScreen() {
      getEncounter.mockResolvedValue({ ...encounter(), best_of: 1, teams: seats(1, 0) } as unknown as Encounter);
      mockStates(
        readyState({
          session: session({ kind: "map" }),
          is_complete: true,
          viewer_team_id: null,
          games: [confirmed(1, 21, 1, 0)],
          pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
        }),
        readyState({
          session: session({ kind: "hero" }),
          is_complete: true,
          viewer_team_id: null,
          ...acts([{ side: "home", itemId: 101 }]),
          ...bansBy("home")
        })
      );
    }
    const retryButton = () =>
      Array.from(document.body.querySelectorAll<HTMLElement>('[role="alert"] button')).find(
        (button) => button.textContent?.trim() === ROOM.retry
      );

    for (const [name, screen, marker] of [
      ["map-result", mapResultScreen, ROOM.mapResult.report],
      ["closing", closingScreen, ROOM.heroBans.seriesTitle]
    ] as const) {
      it(`${name} screen: a failed metadata read says so, keeps the room, and a retry brings the bans back`, async () => {
        screen();
        getMetadata.mockRejectedValue(new Error("metadata down"));
        await render();
        await settle(5);

        const alert = document.body.querySelector('[role="alert"]');
        expect(alert?.textContent).toContain(ROOM.heroBans.metadataError);
        expect(document.body.querySelector("[data-hero-bans]")).toBeNull();
        // The rest of the screen is intact: only the bans' display settings are missing.
        expect(document.body.textContent).toContain(marker);

        getMetadata.mockResolvedValue(OW_METADATA);
        await act(async () => retryButton()!.click());
        await untilBans();

        expect(document.body.querySelector("[data-hero-bans]")).not.toBeNull();
        expect(document.body.textContent).toContain("Hero 101");
        expect(document.body.textContent).not.toContain(ROOM.heroBans.metadataError);
      });

      it(`${name} screen: a slow metadata read shows neither bans nor an error, then the bans`, async () => {
        screen();
        const slow = Promise.withResolvers<typeof OW_METADATA>();
        getMetadata.mockReturnValue(slow.promise);
        await render();
        await settle(5);

        expect(document.body.querySelector("[data-hero-bans]")).toBeNull();
        expect(document.body.textContent).not.toContain(ROOM.heroBans.metadataError);
        expect(document.body.textContent).toContain(marker);

        await act(async () => slow.resolve(OW_METADATA));
        await untilBans();

        expect(document.body.querySelector("[data-hero-bans]")).not.toBeNull();
        expect(document.body.textContent).not.toContain(ROOM.heroBans.metadataError);
      });
    }
  });

  it("states a flat hero pool once, not once per map", async () => {
    // A round-less pool bans for the whole series; repeating it under every map
    // would invent per-map decisions nobody made.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      teams: seats(2, 0)
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: null,
        games: [confirmed(1, 21, 2, 1), confirmed(2, 22, 2, 0)],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: null,
        ...acts([{ side: "home", itemId: 101, round: null }]),
        pool: [entry({ id: 3, item_id: 101, round: null, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME })]
      })
    );
    await render();
    await untilBans();

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
            viewer_team_id: null,
            games: [confirmed(1, 21, 2, 1)],
            pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
          })
        : readyState({
            session: session({ kind: "hero" }),
            is_complete: true,
            viewer_team_id: null,
            sequence: [step({ index: 0 })],
            pool: [entry({ id: 3, item_id: 101, round: 1, status: "available" })]
          })
    );
    await render();

    expect(document.body.textContent).not.toContain(ROOM.heroBans.seriesTitle);
    expect(document.body.querySelector("[data-hero-bans]")).toBeNull();
  });

  it("charts a confirmed position's accepted score with no Match row at all", async () => {
    // A scrim writes no `matches.match` rows, so the filmstrip's score comes
    // from the game the captains confirmed — otherwise every map of a scrim
    // showed as played with nothing on it, which is what made the loop look
    // stuck even though it was advancing correctly.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      teams: seats(1, 0),
      matches: []
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        games: [confirmed(1, 21, 2, 1), game({ position: 2, map_id: 22 })],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: HOME,
        sequence: [step({ index: 0 })],
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

  it("shows no score for a position whose captains disagree", async () => {
    // A dispute is exactly when there is no accepted number, and the server
    // will not advance the series either — inventing one here would tell the
    // captains the map was settled.
    getEncounter.mockResolvedValue({
      ...encounter(),
      best_of: 3,
      matches: []
    } as unknown as Encounter);
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: HOME,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })],
        games: [
          game({
            position: 1,
            map_id: 21,
            state: "disputed",
            claims: [
              { claimant_team_id: HOME, basis_version: 1, results: lines(2, 1) },
              { claimant_team_id: AWAY, basis_version: 1, results: lines(0, 2) }
            ]
          })
        ]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: HOME,
        sequence: [step({ index: 0 })],
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
      teams: seats(0, 0)
    } as unknown as Encounter);
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      readyState({
        session: session({ kind: "hero", status: "completed" }),
        is_complete: true,
        pool: [
          entry({ id: 3, item_id: 101, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: HOME }),
          entry({ id: 4, item_id: 102, round: 1, status: "banned", picked_by_kind: "team", picked_by_team_id: AWAY })
        ]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.mapResult.pickMap);
    expect(document.body.textContent).not.toContain(ROOM.finalReport.title);
  });

  it("holds the hero phase closed until the map it bans for is known", async () => {
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: [step({ index: 0 })],
        is_complete: true,
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 1 })]
      }),
      unavailableState("waiting_map", { [HOME]: true, [AWAY]: true })
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
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 1, item_id: 21 })]
      }),
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true })
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
        sequence: [step({ index: 0 }), step({ index: 1, actors: [AWAY] })],
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
        { id: 101, name: "Ana", slug: "ana", image_path: "", attrs: { class: "support" } },
        {
          id: 102,
          name: "Reinhardt",
          slug: "reinhardt",
          image_path: "",
          attrs: { class: "tank" }
        }
      ]
    });
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        sequence: [step({ index: 0 }), step({ index: 1, actors: [AWAY] })],
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
        sequence: [step({ index: 0, round: null })],
        current_step: step({ index: 0, round: null }),
        current_step_index: 0,
        acting_team_ids: [HOME],
        pool: [entry({ id: 1, item_id: 21 })],
        expected_action: "ban",
        viewer_can_act: true,
        allowed_actions: ["ban"],
        eligible: { item_ids: [21], by_target: null }
      }),
      unavailableState("not_configured")
    );
    performPickBanAction.mockResolvedValue(
      readyState({ session: session({ kind: "map" }), is_complete: true })
    );
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

describe("side selection", () => {
  const SIDE = en.pickBan.room.sides.lol;

  /** A League side step: one side choice by `actors`, round 1 unless told otherwise. */
  function sideStep(overrides: Partial<PickBanResolvedStep> & { index: number }): PickBanResolvedStep {
    return step({ action: "side_pick", lifetime: null, ...overrides });
  }

  /** The hero room on its side step, with the champion pool the organizer had to save (R1). */
  function sideRoom(overrides: Partial<PickBanState> = {}): PickBanState {
    const current = sideStep({ index: 0 });
    return readyState({
      session: session({ kind: "hero" }),
      sequence: [current],
      current_step: current,
      current_step_index: 0,
      acting_team_ids: [HOME],
      current_round: 1,
      expected_action: "side_pick",
      viewer_can_act: true,
      allowed_actions: ["side_pick"],
      sides: ["blue", "red"],
      starting_sides: [],
      pool: HEROES.map((hero, index) => entry({ id: 30 + index, item_id: hero.id, round: 1 })),
      ...overrides
    });
  }

  /** A choice group by the visible text that labels it. */
  function choiceGroup(label: string): HTMLElement {
    const found = Array.from(document.body.querySelectorAll<HTMLElement>('[role="group"]')).find(
      (group) =>
        document.getElementById(group.getAttribute("aria-labelledby") ?? "")?.textContent?.trim() === label
    );
    if (!found) throw new Error(`no choice group labelled "${label}"`);
    return found;
  }

  const buttonIn = (scope: ParentNode, label: string) =>
    Array.from(scope.querySelectorAll<HTMLButtonElement>("button")).find(
      (button) => button.textContent?.trim() === label
    );
  const confirmSide = (side: string) => buttonIn(document.body, ROOM.captain.confirmSide.replace("{side}", side));

  async function nextAnswer(hero: PickBanState) {
    mockStates(unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), hero);
    await act(async () => {
      await roomClient.invalidateQueries();
    });
    await settle();
  }

  beforeEach(() => {
    getEncounter.mockResolvedValue({ ...encounter(), discipline: "lol" } as Encounter);
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    performPickBanAction.mockResolvedValue(readyState({ session: session({ kind: "hero" }), is_complete: true }));
  });

  it("asks the captain for a side instead of a champion, and sends index 0 for the first side", async () => {
    mockStates(unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), sideRoom());
    await render();

    // No pool on a side step: no champion tile to misclick into a 400.
    expect(document.body.textContent).not.toContain(ROOM.hero.title);
    expect(document.body.querySelector('button[aria-label^="Hero 101"]')).toBeNull();

    const group = choiceGroup(ROOM.captain.chooseSideHint);
    const blue = buttonIn(group, SIDE.blue)!;
    const red = buttonIn(group, SIDE.red)!;
    // Native buttons: in the tab order, Enter/Space activate them, and the pressed state is announced.
    for (const button of [blue, red]) {
      expect(button.getAttribute("type")).toBe("button");
      expect(button.disabled).toBe(false);
      expect(button.getAttribute("aria-pressed")).toBe("false");
    }
    blue.focus();
    expect(document.activeElement).toBe(blue);
    expect(confirmSide("—")?.disabled).toBe(true);

    await act(async () => blue.click());
    await settle();
    expect(blue.getAttribute("aria-pressed")).toBe("true");
    expect(red.getAttribute("aria-pressed")).toBe("false");

    await act(async () => confirmSide(SIDE.blue)!.click());
    await settle();

    expect(performPickBanAction).toHaveBeenCalledWith("hero", 4242, { item_id: 0, action: "side_pick" });
  });

  it("drops the chosen side when the room moves to another step", async () => {
    mockStates(unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), sideRoom());
    await render();
    await act(async () => buttonIn(choiceGroup(ROOM.captain.chooseSideHint), SIDE.red)!.click());
    await settle();
    expect(confirmSide(SIDE.red)).toBeTruthy();

    // The next round's side step: same action, new step — the old choice must not carry over.
    const next = sideStep({ index: 1, round: 2, actors: [HOME] });
    await nextAnswer(
      sideRoom({
        sequence: [sideStep({ index: 0 }), next],
        submissions: [submission({ step_index: 0, encounter_team_id: HOME, items: [{ item_id: 1, target_player_id: null }] })],
        current_step: next,
        current_step_index: 1,
        current_round: 2
      })
    );

    const group = choiceGroup(ROOM.captain.chooseSideHint);
    expect(group.querySelector('[aria-pressed="true"]')).toBeNull();
    expect(confirmSide("—")?.disabled).toBe(true);
    expect(performPickBanAction).not.toHaveBeenCalled();
  });

  it("forgets the chosen side when its step closes and is undone back open, under the same step index", async () => {
    // Custom side → ban room: the captain picks Red locally, the step is answered elsewhere, then mutually undone
    // before any ban. The reopened step has the very same index and attempt; the old choice must not come back.
    const side = sideStep({ index: 0 });
    const ban = step({ index: 1, actors: [AWAY] });
    const open = sideRoom({ sequence: [side, ban] });
    mockStates(unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), open);
    await render();
    await act(async () => buttonIn(choiceGroup(ROOM.captain.chooseSideHint), SIDE.red)!.click());
    await settle();
    expect(confirmSide(SIDE.red)).toBeTruthy();

    await nextAnswer(
      sideRoom({
        sequence: [side, ban],
        submissions: [submission({ step_index: 0, encounter_team_id: HOME, items: [{ item_id: 0, target_player_id: null }] })],
        current_step: ban,
        current_step_index: 1,
        acting_team_ids: [AWAY],
        expected_action: "ban",
        viewer_can_act: false,
        allowed_actions: []
      })
    );
    await nextAnswer(open);

    const group = choiceGroup(ROOM.captain.chooseSideHint);
    expect(group.querySelector('[aria-pressed="true"]')).toBeNull();
    expect(confirmSide("—")?.disabled).toBe(true);
    expect(confirmSide(SIDE.red)).toBeUndefined();
  });

  it("keeps a champion picked on the step before out of the side step, and sends the side's index", async () => {
    const ban = step({ index: 0 });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      sideRoom({
        sequence: [ban, sideStep({ index: 1 })],
        current_step: ban,
        expected_action: "ban",
        allowed_actions: ["ban"],
        eligible: { item_ids: [101, 102, 103], by_target: null }
      })
    );
    await render();
    await act(async () => document.body.querySelector<HTMLButtonElement>('button[aria-label^="Hero 101"]')!.click());
    await settle();
    expect(buttonIn(document.body, ROOM.captain.confirmBan.replace("{item}", "Hero 101"))).toBeTruthy();

    const side = sideStep({ index: 1 });
    await nextAnswer(
      sideRoom({
        sequence: [ban, side],
        current_step: side,
        current_step_index: 1,
        submissions: [submission({ step_index: 0, encounter_team_id: HOME, items: [{ item_id: 102, target_player_id: null }] })]
      })
    );

    expect(document.querySelector('[aria-label="' + ROOM.commandBar + '"]')?.textContent).not.toContain("Hero 101");
    expect(confirmSide("—")?.disabled).toBe(true);
    await act(async () => buttonIn(choiceGroup(ROOM.captain.chooseSideHint), SIDE.red)!.click());
    await settle();
    await act(async () => confirmSide(SIDE.red)!.click());
    await settle();

    expect(performPickBanAction).toHaveBeenCalledWith("hero", 4242, { item_id: 1, action: "side_pick" });
  });

  it("shows a viewer who is not on the clock the sides, but not as choices", async () => {
    getMyRole.mockResolvedValue({ encounter_team_id: AWAY, slot: 2 });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      sideRoom({ viewer_team_id: AWAY, viewer_can_act: false, allowed_actions: [] })
    );
    await render();

    const group = choiceGroup(ROOM.captain.chooseSideHint);
    expect(buttonIn(group, SIDE.blue)?.disabled).toBe(true);
    expect(buttonIn(group, SIDE.red)?.disabled).toBe(true);
    expect(confirmSide("—")).toBeUndefined();
  });

  it("speaks in sides on the timeline, the undo and the assignment, never in champions", async () => {
    const chosen = sideStep({ index: 0 });
    const ban = step({ index: 1, actors: [AWAY] });
    mockStates(
      unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
      sideRoom({
        sequence: [chosen, ban],
        submissions: [submission({ step_index: 0, encounter_team_id: HOME, items: [{ item_id: 0, target_player_id: null }] })],
        current_step: ban,
        current_step_index: 1,
        acting_team_ids: [AWAY],
        expected_action: "ban",
        viewer_can_act: false,
        allowed_actions: [],
        starting_sides: [{ game_id: 901, position: 1, sides: { [HOME]: "blue", [AWAY]: "red" } }],
        undo: { requested_by_team_id: null, step_index: 0, item_ids: [0], action: "side_pick", encounter_team_id: HOME }
      })
    );
    await render();

    const row = document.body.querySelector('[data-pick-ban-step="0"]');
    expect(row?.textContent).toContain(ROOM.step.side.side_pick.replace("{team}", "Bright Wolves"));
    expect(row?.textContent).toContain(SIDE.blue);

    const undo = Array.from(document.body.querySelectorAll("div")).find(
      (node) => node.firstElementChild?.textContent === ROOM.undo.label
    );
    expect(undo?.textContent).toContain(SIDE.blue);

    const assignment = document.body.querySelector('[data-side-assignment="1"]');
    expect(assignment?.textContent).toContain(
      ROOM.sideAssignment.replace("{side}", SIDE.blue).replace("{team}", "Bright Wolves")
    );
    expect(assignment?.textContent).toContain(
      ROOM.sideAssignment.replace("{side}", SIDE.red).replace("{team}", "Quiet Foxes")
    );
    expect(document.body.textContent).not.toContain("Hero #0");
    expect(document.body.textContent).not.toContain("Hero #1");
  });

  describe("for an organizer", () => {
    beforeEach(() => {
      getMyRole.mockResolvedValue({ encounter_team_id: null, slot: null });
      usePermissionsMock.mockReturnValue({
        isSuperuser: true,
        isWorkspaceAdmin: () => true,
        hasWorkspacePermission: () => true
      });
      adminPickBanAct.mockResolvedValue({});
    });

    const adminSection = () =>
      Array.from(document.body.querySelectorAll("section")).find(
        (section) => section.querySelector("h2")?.textContent === ROOM.admin.title
      )!;

    it("chooses a side for either team without a champion tile", async () => {
      mockStates(
        unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
        sideRoom({ viewer_team_id: null, viewer_can_act: false, allowed_actions: [] })
      );
      await render();
      await showAdminUi();

      const panel = adminSection();
      const actionField = Array.from(panel.querySelectorAll("div")).find(
        (node) => node.firstElementChild?.textContent === ROOM.admin.actionLabel
      );
      expect(actionField?.textContent).toBe(`${ROOM.admin.actionLabel}${ROOM.action.side_pick}`);
      expect(panel.textContent).not.toContain(ROOM.admin.selectItemFirst);

      // The team override is kept; the side is the step's own choice.
      await act(async () => buttonIn(panel, "Quiet Foxes")!.click());
      await settle();
      await act(async () => buttonIn(choiceGroup(ROOM.admin.sideChoiceLabel), SIDE.blue)!.click());
      await settle();
      await act(async () => buttonIn(panel, `${ROOM.admin.confirm}: ${SIDE.blue}`)!.click());
      await settle();

      expect(adminPickBanAct).toHaveBeenCalledWith(4242, {
        kind: "hero",
        encounter_team_id: AWAY,
        item_id: 0,
        action: "side_pick"
      });
    });

    it("drops the organizer's side when the team it was chosen for changes, and when the step is reopened", async () => {
      const open = sideRoom({ viewer_team_id: null, viewer_can_act: false, allowed_actions: [] });
      mockStates(unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), open);
      await render();
      await showAdminUi();
      const panel = adminSection();
      const adminSides = () => choiceGroup(ROOM.admin.sideChoiceLabel);
      const perform = () =>
        Array.from(panel.querySelectorAll<HTMLButtonElement>("button")).find((button) =>
          button.textContent?.trim().startsWith(ROOM.admin.confirm)
        )!;

      // Chosen for the team on the clock, then the override moves to the other team: the choice is gone.
      await act(async () => buttonIn(adminSides(), SIDE.blue)!.click());
      await settle();
      expect(perform().textContent?.trim()).toBe(`${ROOM.admin.confirm}: ${SIDE.blue}`);
      await act(async () => buttonIn(panel, "Quiet Foxes")!.click());
      await settle();
      expect(adminSides().querySelector('[aria-pressed="true"]')).toBeNull();
      expect(perform().disabled).toBe(true);

      // Chosen again, then an organizer reopens the step (a new attempt, a new clock): gone again.
      await act(async () => buttonIn(adminSides(), SIDE.red)!.click());
      await settle();
      expect(perform().disabled).toBe(false);
      await nextAnswer({
        ...open,
        session: session({ kind: "hero", current_step_started_at: "2026-08-01T10:05:00Z" }),
        submissions: [submission({ step_index: 0, encounter_team_id: AWAY, attempt: 2, state: "draft", items: [] })]
      });
      expect(adminSides().querySelector('[aria-pressed="true"]')).toBeNull();
      expect(perform().disabled).toBe(true);
      expect(adminPickBanAct).not.toHaveBeenCalled();
    });

    /** Round 1's side is picked: a side-only round has no step left until its game is played. */
    function sidePicked(): PickBanState {
      return sideRoom({
        viewer_team_id: null,
        viewer_can_act: false,
        allowed_actions: [],
        submissions: [submission({ step_index: 0, encounter_team_id: HOME, items: [{ item_id: 0, target_player_id: null }] })],
        current_step: null,
        current_step_index: null,
        acting_team_ids: [],
        expected_action: null,
        is_complete: true,
        starting_sides: [{ game_id: 901, position: 1, sides: { [HOME]: "blue", [AWAY]: "red" } }]
      });
    }

    it("reopens a settled side pick whose game is not played yet", async () => {
      adminPickBanReopen.mockResolvedValue({});
      mockStates(
        { ...unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), games: [game({ position: 1 })] },
        sidePicked()
      );
      await render();
      await showAdminUi();

      await act(async () => buttonIn(adminSection(), ROOM.admin.reopen)!.click());
      await settle();
      expect(adminPickBanReopen).toHaveBeenCalledWith(4242, "hero");
    });

    it.each([
      ["claimed", game({ position: 1, claims: [{ claimant_team_id: HOME, basis_version: 1, results: lines(1, 0) }] })],
      ["confirmed", confirmed(1, 21, 1, 0)]
    ])("never offers to reopen a side its %s game was played on", async (_label, played) => {
      mockStates(
        { ...unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), games: [played] },
        sidePicked()
      );
      await render();
      await showAdminUi();

      expect(buttonIn(adminSection(), ROOM.admin.reset)).toBeTruthy();
      expect(buttonIn(adminSection(), ROOM.admin.reopen)).toBeUndefined();
    });

    it("corrects a hero-only room's games, and names a correction the next game already depends on", async () => {
      correctGameResult.mockRejectedValue(
        new ApiError(409, [{ msg: "Game 2's pick-ban already started", code: "dependent_round_started" }])
      );
      const next = sideStep({ index: 1, round: 2 });
      mockStates(
        { ...unavailableState("not_configured", { [HOME]: true, [AWAY]: true }), games: [confirmed(1, 21, 2, 1)] },
        sideRoom({
          viewer_team_id: null,
          viewer_can_act: false,
          allowed_actions: [],
          sequence: [sideStep({ index: 0 }), next],
          current_step: next,
          current_step_index: 1,
          current_round: 2
        })
      );
      await render();
      await showAdminUi();

      const row = document.body.querySelector<HTMLElement>('[data-game-correction="901"]');
      expect(row).not.toBeNull();
      const reason = row!.querySelector<HTMLInputElement>(`input[aria-label="${ROOM.admin.correctReason}"]`)!;
      await act(async () => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(reason, "wrong winner");
        reason.dispatchEvent(new Event("input", { bubbles: true }));
      });
      await act(async () => buttonIn(row!, ROOM.admin.correctSubmit)!.click());
      await settle();

      expect(correctGameResult).toHaveBeenCalledWith(4242, 901, expect.objectContaining({ reason: "wrong winner" }));
      expect(notify.error).toHaveBeenCalledWith(ROOM.admin.dependentRoundStarted);
      expect(notify.apiError).not.toHaveBeenCalled();
    });

    it("reads a side pick back in the room history by the side's name", async () => {
      getPregameRoomHistory.mockResolvedValue({
        encounter_id: 4242,
        entries: [
          {
            id: "room:1",
            at: "2026-10-02T11:58:00Z",
            origin: "room",
            kind: "hero",
            action: "acted",
            source: "captain",
            side: null,
            encounter_team_id: HOME,
            actor_auth_user_id: 9,
            actor_name: "Captain Bright",
            reason: null,
            data: { step_index: 0, round: 1, action: "side_pick", item_id: 0 }
          }
        ]
      });
      mockStates(
        unavailableState("not_configured", { [HOME]: true, [AWAY]: true }),
        sideRoom({ viewer_team_id: null, viewer_can_act: false, allowed_actions: [] })
      );
      await render();
      await showAdminUi();
      await act(async () =>
        Array.from(document.body.querySelectorAll("button"))
          .find((button) => button.textContent?.includes(ROOM.history.toggle))!
          .click()
      );
      await settle();

      const log = document.body.querySelector<HTMLElement>(`[aria-label="${ROOM.history.label}"]`);
      expect(log?.textContent).toContain(`Bright Wolves ${ROOM.history.verb.side_pick} ${SIDE.blue}`);
      expect(log?.textContent).not.toContain("#0");
    });
  });
});

describe("admin controls", () => {
  it("names the step's own action instead of offering the organizer a choice of three", async () => {
    // A v2 step names what it accepts, so "ban / pick / protect" next to a
    // protect step was three buttons of which two produced a 400.
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        sequence: [step({ index: 0, action: "protect", actors: [AWAY] })],
        current_step: step({ index: 0, action: "protect", actors: [AWAY] }),
        current_step_index: 0,
        acting_team_ids: [AWAY],
        current_round: 1,
        pool: [entry({ id: 1, item_id: 101, round: 1 })]
      })
    );
    await render();
    await showAdminUi();

    expect(document.body.textContent).toContain(ROOM.admin.title);
    const actionField = Array.from(document.body.querySelectorAll("div")).find(
      (node) => node.firstElementChild?.textContent === ROOM.admin.actionLabel
    );
    expect(actionField?.textContent).toBe(`${ROOM.admin.actionLabel}${ROOM.action.protect}`);
    // No picker: the organizer cannot ask this step for a ban.
    expect(
      Array.from(document.body.querySelectorAll("button")).filter(
        (button) => button.textContent?.trim() === ROOM.action.ban
      )
    ).toHaveLength(0);
  });

  it("builds an absent captain's blind draft out of the pool, then reopens the step", async () => {
    // A blind step has no tile-by-tile path for a side the organizer is not —
    // it used to take item IDs typed into a box, which is a pool nobody can see.
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    adminPickBanSubmit.mockResolvedValue(readyState({ session: session({ kind: "hero" }) }));
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        ...blindRound(),
        dispute: { available: false, step_index: 0, attempts_used: 0, max: 1 }
      })
    );
    await render();

    const tile = (name: string) =>
      document.body.querySelector<HTMLButtonElement>(`button[aria-label^="${name}"]`);
    expect(tile("Tank A")?.disabled).toBe(true);
    await showAdminUi();
    expect(tile("Tank A")?.disabled).toBe(false);
    await act(async () => tile("Tank A")!.click());
    await settle();
    await act(async () => tile("Support A")!.click());
    await settle();

    // The clicks are the organizer's, never the viewer's own draft.
    expect(submitDraft).not.toHaveBeenCalled();

    const submit = Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === ROOM.admin.submitConfirm
    );
    await act(async () => submit!.click());
    await settle();

    expect(adminPickBanSubmit).toHaveBeenCalledWith(4242, {
      kind: "hero",
      encounter_team_id: HOME,
      items: [
        { item_id: 201, target_player_id: null },
        { item_id: 203, target_player_id: null }
      ],
      lock: true
    });

    const reopen = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.admin.reopen)
    );
    await act(async () => reopen!.click());
    await settle();
    expect(adminPickBanReopen).toHaveBeenCalledWith(4242, "hero");

    const toggle = Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === ROOM.admin.hideUi
    );
    await act(async () => toggle!.click());
    await settle();
    expect(tile("Tank A")?.disabled).toBe(true);
  });

  it("names the opponent player each of an absent captain's bans is for", async () => {
    // A per-player step is two choices per ban, and the organizer makes both
    // from the panel's roster of the OTHER side plus this pool.
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    getAllHeroes.mockResolvedValue({ results: HERO_CATALOG });
    adminPickBanSubmit.mockResolvedValue(readyState({ session: session({ kind: "hero" }) }));
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        ...blindRound({ target: "opponent_player" }),
        targets: {
          [HOME]: [],
          [AWAY]: [
            {
              player_id: 55,
              name: "Foxy",
              role: { dimension: "player_role", role: "tank" },
              is_substitution: false,
              division: 7
            },
            {
              player_id: 56,
              name: "Vixen",
              role: { dimension: "player_role", role: "tank" },
              is_substitution: true,
              division: 12
            }
          ]
        }
      })
    );
    await render();
    await showAdminUi();

    const byLabel = (label: string) =>
      Array.from(document.body.querySelectorAll("button")).find(
        (button) => button.textContent?.trim() === label
      );
    const tile = (name: string) =>
      document.body.querySelector<HTMLButtonElement>(`button[aria-label^="${name}"]`);

    // Home is the side being acted for, so the players on offer are away's.
    await act(async () => byLabel("Vixen")!.click());
    await settle();
    await act(async () => tile("Tank B")!.click());
    await settle();
    await act(async () => byLabel("Foxy")!.click());
    await settle();
    await act(async () => tile("Tank A")!.click());
    await settle();

    await act(async () => byLabel(ROOM.admin.submitConfirm)!.click());
    await settle();

    expect(adminPickBanSubmit).toHaveBeenCalledWith(4242, {
      kind: "hero",
      encounter_team_id: HOME,
      items: [
        { item_id: 202, target_player_id: 56 },
        { item_id: 201, target_player_id: 55 }
      ],
      lock: true
    });
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
        games: [confirmed(1, 21, 2, 1), game({ position: 2, map_id: 22 })],
        pool: [
          entry({ id: 10, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 11, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({
          kind: "hero",
          status: "completed",
          awaiting_choice: true,
          pending_chooser_team_id: AWAY
        }),
        is_complete: true,
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 1, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();
    await showAdminUi();

    expect(document.body.textContent).toContain(ROOM.admin.electLabel);
    const panel = document.body.textContent ?? "";
    expect(panel).toContain("Bright Wolves");
    expect(panel).toContain("Quiet Foxes");
  });

  it("omits the reset/act panel for a non-admin captain", async () => {
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero" }),
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 1, item_id: 101 })]
      })
    );
    await render();

    expect(document.body.textContent).not.toContain(ROOM.admin.title);
    expect(document.body.textContent).not.toContain(ROOM.admin.showUi);
  });

  it("lets an organizer mark an absent captain's side ready", async () => {
    // The gate holds BOTH kinds' sessions shut at once, so one unreachable
    // captain freezes the entire room — and the captains' own button only ever
    // confirms the viewer's own side.
    usePermissionsMock.mockReturnValue({
      isSuperuser: false,
      isWorkspaceAdmin: () => false,
      hasWorkspacePermission: () => true
    });
    setEncounterReadiness.mockResolvedValue({ readiness: { [HOME]: false, [AWAY]: true } });
    mockStates(unavailableState("not_ready"), unavailableState("not_configured"));
    await render();

    expect(document.body.textContent).not.toContain(ROOM.admin.readinessTitle);
    const toggle = Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === ROOM.admin.showUi
    );
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    await showAdminUi();
    expect(toggle?.getAttribute("aria-expanded")).toBe("true");

    const buttons = Array.from(document.body.querySelectorAll("button")).filter(
      (button) => button.textContent?.trim() === ROOM.admin.readinessSet
    );
    expect(buttons).toHaveLength(2);
    const away = buttons.find((button) =>
      button.parentElement?.textContent?.includes("Quiet Foxes")
    );
    await act(async () => away!.click());
    await settle();

    expect(setEncounterReadiness).toHaveBeenCalledWith(4242, { encounter_team_id: AWAY, ready: true });

    await act(async () => toggle!.click());
    await settle();
    expect(toggle?.getAttribute("aria-expanded")).toBe("false");
    expect(document.body.textContent).not.toContain(ROOM.admin.readinessTitle);
  });

  it("keeps the readiness override off the waiting screen for a captain", async () => {
    getMyRole.mockResolvedValue({ encounter_team_id: HOME, slot: 1 });
    mockStates(unavailableState("not_ready"), unavailableState("not_configured"));
    await render();

    expect(document.body.textContent).toContain(ROOM.ready.button);
    expect(document.body.textContent).not.toContain(ROOM.admin.readinessTitle);
  });

  it("still reaches the hero session's reset on the closing screen", async () => {
    // The overrides used to live inside the pick-ban board, so once the series
    // was over there was no screen left that rendered them at all.
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        viewer_team_id: null,
        games: [confirmed(1, 21, 2, 1)],
        pool: [entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 })]
      }),
      readyState({
        session: session({ kind: "hero" }),
        is_complete: true,
        viewer_team_id: null,
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();
    await showAdminUi();

    const tab = Array.from(document.body.querySelectorAll<HTMLElement>('[role="tab"]')).find(
      (node) => node.textContent?.trim() === ROOM.phase.hero
    );
    await act(async () => tab!.click());
    await settle();

    const byLabel = (label: string) =>
      Array.from(document.body.querySelectorAll("button")).find(
        (button) => button.textContent?.trim() === label
      );
    await act(async () => byLabel(ROOM.admin.reset)!.click());
    await settle();
    await act(async () => byLabel(ROOM.admin.resetConfirmAction)!.click());
    await settle();

    expect(resetPickBanSession).toHaveBeenCalledWith(4242, "hero");
  });
});

describe("organizer session controls", () => {
  /** Admin on an open, timed hero step — the state every control needs. */
  function openHeroStep(sessionOverrides: Partial<PickBanSession> = {}) {
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    const open = step({ index: 0, timer_seconds: 60 });
    mockStates(
      unavailableState("not_configured"),
      readyState({
        session: session({ kind: "hero", ...sessionOverrides }),
        sequence: [open],
        current_step: open,
        current_step_index: 0,
        acting_team_ids: [HOME],
        current_round: 1,
        step_deadline: new Date(Date.now() + 45_000).toISOString(),
        pool: [entry({ id: 1, item_id: 101, round: 1 })]
      })
    );
  }

  const byLabel = (label: string) =>
    Array.from(document.body.querySelectorAll("button")).find(
      (button) => button.textContent?.trim() === label
    );

  it("pauses the session on the kind the panel is acting on", async () => {
    openHeroStep();
    await render();
    await showAdminUi();

    await act(async () => byLabel(ROOM.admin.pause)!.click());
    await settle();

    expect(adminPickBanPause).toHaveBeenCalledWith(4242, { kind: "hero", paused: true });
  });

  it("extends the open step's timer and cancels the session with a reason", async () => {
    openHeroStep();
    await render();
    await showAdminUi();

    await act(async () => byLabel(ROOM.admin.extendBy.replace("{seconds}", "60"))!.click());
    await settle();
    expect(adminPickBanExtend).toHaveBeenCalledWith(4242, { kind: "hero", seconds: 60 });

    await act(async () => byLabel(ROOM.admin.cancelSession)!.click());
    await settle();
    const confirm = byLabel(ROOM.admin.cancelConfirmAction)!;
    // A cancel with no reason recorded is a cancel nobody can explain later.
    expect(confirm.hasAttribute("disabled")).toBe(true);

    const reason = document.body.querySelector<HTMLInputElement>(
      `input[aria-label="${ROOM.admin.cancelReason}"]`
    )!;
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value"
      )!.set!;
      setter.call(reason, "both captains agreed");
      reason.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await settle();

    await act(async () => byLabel(ROOM.admin.cancelConfirmAction)!.click());
    await settle();

    expect(adminPickBanCancel).toHaveBeenCalledWith(4242, {
      kind: "hero",
      reason: "both captains agreed"
    });
  });

  it("tells everyone the room is paused and stops the countdown", async () => {
    // The deadline is still in the fixture (a cached state), so the clock has
    // to be stopped by the pause itself and not by the absent `step_deadline`.
    openHeroStep({ paused_at: "2026-08-01T10:05:00Z" });
    await render();
    await showAdminUi();

    expect(document.body.textContent).toContain(ROOM.pausedBanner);
    expect(document.body.textContent).not.toContain(ROOM.timer.label);
    // Resume is what an organizer gets offered once it is held.
    expect(byLabel(ROOM.admin.resume)).toBeTruthy();
  });

  it("prefills a technical loss with the score the series would end on", async () => {
    getEncounter.mockResolvedValue({ ...encounter(), best_of: 3 } as unknown as Encounter);
    openHeroStep();
    adminTechnicalLoss.mockResolvedValue({});
    await render();
    await showAdminUi();

    await act(async () => byLabel(ROOM.admin.technicalLoss)!.click());
    await settle();

    const field = (label: string) =>
      document.body.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`)!;
    const home = field(ROOM.admin.correctScore.replace("{team}", "Bright Wolves"));
    const away = field(ROOM.admin.correctScore.replace("{team}", "Quiet Foxes"));
    // Bo3 at 0:0, away forfeits: the home side takes the two maps it needs.
    expect(home.value).toBe("2");
    expect(away.value).toBe("0");

    const reason = field(ROOM.admin.technicalLossReason);
    await act(async () => {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype,
        "value"
      )!.set!;
      setter.call(reason, "no show");
      reason.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await settle();

    await act(async () => byLabel(ROOM.admin.technicalLossAction)!.click());
    await settle();

    expect(adminTechnicalLoss).toHaveBeenCalledWith(4242, {
      loser_team_id: AWAY,
      results: [
        { encounter_team_id: HOME, score: 2 },
        { encounter_team_id: AWAY, score: 0 }
      ],
      reason: "no show"
    });
  });

  it("drops the hero phase for the rest of the series once its session is cancelled", async () => {
    // Same shape as the "still catching up" case, except an organizer killed
    // the hero session — map 2 goes straight to its report instead of waiting
    // for bans that will never open.
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        is_complete: true,
        games: [confirmed(1, 21, 2, 1), game({ position: 2, map_id: 22 })],
        pool: [
          entry({ id: 1, item_id: 21, round: 1, status: "picked", action_index: 2 }),
          entry({ id: 2, item_id: 22, round: 2, status: "picked", action_index: 5 })
        ]
      }),
      readyState({
        session: session({ kind: "hero", status: "cancelled" }),
        sequence: [step({ index: 0 })],
        pool: [entry({ id: 3, item_id: 101, round: 1, status: "banned" })]
      })
    );
    await render();

    expect(document.body.textContent).toContain(ROOM.mapResult.report);
    expect(document.body.textContent).not.toContain(ROOM.hero.title);
    expect(document.body.textContent).toContain(
      ROOM.cancelledNotice.replace("{phase}", ROOM.phase.hero)
    );
  });
});

describe("room history", () => {
  /** One journal line, room-origin unless a case says otherwise. */
  function historyEntry(overrides: Record<string, unknown>) {
    return {
      id: "room:1",
      at: "2026-10-02T11:58:00Z",
      origin: "room",
      kind: "map",
      source: "captain",
      side: null,
      actor_auth_user_id: null,
      actor_name: null,
      reason: null,
      data: {},
      ...overrides
    };
  }

  async function openHistory() {
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    mockStates(
      readyState({
        session: session({ kind: "map" }),
        sequence: [step({ index: 0 })],
        current_step: step({ index: 0 }),
        pool: [entry({ id: 1, item_id: 21, round: 1 })]
      }),
      unavailableState("not_configured")
    );
    await render();
    await showAdminUi();
    const toggle = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.history.toggle)
    );
    await act(async () => toggle!.click());
    await settle();
    return document.body.querySelector<HTMLElement>(`[aria-label="${ROOM.history.label}"]`)!;
  }

  it("reads back who did what, newest first", async () => {
    // The room's own state says a map is banned; only the journal says the
    // captain banned it, the clock resolved the next step, and when.
    getPregameRoomHistory.mockResolvedValue({
      encounter_id: 4242,
      entries: [
        historyEntry({
          id: "room:2",
          at: "2026-10-02T11:59:00Z",
          action: "step_timed_out",
          source: "system",
          data: { step_index: 1, policy: "random" }
        }),
        historyEntry({
          id: "room:1",
          action: "acted",
          encounter_team_id: HOME,
          actor_auth_user_id: 9,
          actor_name: "Captain Bright",
          data: { step_index: 0, action: "ban", item_id: 21 }
        })
      ]
    });

    const log = await openHistory();

    const rows = Array.from(log.querySelectorAll("li"));
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain(
      ROOM.history.action.step_timed_out.replace("{step}", "1").replace("{policy}", "random")
    );
    // No actor on a clock event: it reads as the system, not as a blank.
    expect(rows[0].textContent).toContain(ROOM.history.system);
    expect(rows[1].textContent).toContain("Bright Wolves banned Map 21");
    expect(rows[1].textContent).toContain("Captain Bright");
  });

  it("renders an action it has never heard of instead of a blank line", async () => {
    // The vocabulary is the backend's; a line nobody can read is still better
    // than a journal with holes in it.
    getPregameRoomHistory.mockResolvedValue({
      encounter_id: 4242,
      entries: [
        historyEntry({ id: "room:9", action: "quantum_leap", source: "admin", actor_name: "Ref" })
      ]
    });

    const log = await openHistory();

    expect(log.textContent).toContain("quantum_leap");
    expect(log.textContent).toContain("Ref");
  });

  it("stays available on a screen with no session to override", async () => {
    // "Why is this room not open yet" is a journal question, and the readiness
    // gate is exactly where it gets asked.
    usePermissionsMock.mockReturnValue({
      isSuperuser: true,
      isWorkspaceAdmin: () => true,
      hasWorkspacePermission: () => true
    });
    getPregameRoomHistory.mockResolvedValue({ encounter_id: 4242, entries: [] });
    mockStates(unavailableState("not_ready"), unavailableState("not_configured"));
    await render();
    await showAdminUi();

    const toggle = Array.from(document.body.querySelectorAll("button")).find((button) =>
      button.textContent?.includes(ROOM.history.toggle)
    );
    expect(toggle).toBeTruthy();
    await act(async () => toggle!.click());
    await settle();
    expect(document.body.textContent).toContain(ROOM.history.empty);
  });
});
