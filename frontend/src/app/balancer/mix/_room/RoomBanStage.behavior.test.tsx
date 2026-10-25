// @vitest-environment happy-dom
//
// A lobby's Pre-game in the room's centre ends when its ban room does: the bans finished, or a host cancelled the room
// (the match then plays without bans). Either way the room re-reads its lobby exactly once, which then reads Live. The
// stage is mounted the way the room mounts it -- the room's hook reads the state, the shared pick-ban pieces render it
// -- over a mocked server; with a pick preset it also takes each player's pick and the captains' assignment, the
// mocked server answering a write with the room it makes. A host answers the team on the clock from the same bar.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import en from "@/i18n/messages/en.json";
import { notify } from "@/lib/notify";
import type { PickBanSubmitInput } from "@/services/pickBan.service";
import type {
  PickBanEntry,
  PickBanResolvedStep,
  PickBanState,
  PickBanSubmissionItem,
} from "@/types/tournament.types";

import { useMixBanRoom } from "@/app/balancer/mix/_hooks/useMixBanRoom";

import { RoomBanStage } from "./RoomBanStage";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getPickBanState = vi.fn();
const performPickBanAction = vi.fn();
const submitDraft = vi.fn();
const adminPickBanCancel = vi.fn();
const adminPickBanAct = vi.fn();

vi.mock("@/services/pickBan.service", () => ({
  default: {
    getPickBanState: (...args: unknown[]) => getPickBanState(...args),
    performPickBanAction: (...args: unknown[]) => performPickBanAction(...args),
    submitDraft: (...args: unknown[]) => submitDraft(...args),
    disputeStep: vi.fn(),
    undoLastAction: vi.fn(),
    electOpener: vi.fn(),
  },
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    adminPickBanCancel: (...args: unknown[]) => adminPickBanCancel(...args),
    resetPickBanSession: vi.fn(),
    adminPickBanAct: (...args: unknown[]) => adminPickBanAct(...args),
    adminPickBanSubmit: vi.fn(),
    adminPickBanReopen: vi.fn(),
    adminPickBanPause: vi.fn(),
    adminPickBanExtend: vi.fn(),
    adminPickBanElectOpener: vi.fn(),
    adminTechnicalLoss: vi.fn(),
  },
}));
vi.mock("@/services/catalog.service", () => ({
  default: {
    list: async () => ({
      results: [101, 102, 103].map((id) => ({ id, name: `Hero ${id}`, image_path: "", attrs: { class: "damage" } })),
    }),
  },
}));
vi.mock("@/services/discipline.service", () => ({
  default: {
    list: async () => [],
    metadata: async (_axis: unknown, code: string) => ({
      discipline: { code, character_classes: ["tank", "damage", "support"], capabilities: {} },
      dimensions: [],
      roles: [],
    }),
  },
}));
/** Topic -> the board's subscription callbacks, so a case can confirm a subscription the way the hub would. */
const subscriptions = new Map<string, { onEvent: () => void; onSubscribed?: () => void }>();
vi.mock("@/hooks/useRealtimeTopic", () => ({
  useRealtimeTopic: (topic: string, onEvent: () => void, _deps: unknown, onSubscribed?: () => void) => {
    subscriptions.set(topic, { onEvent, onSubscribed });
  },
}));
vi.mock("@/lib/notify", () => ({
  notify: { apiError: vi.fn(), success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const ADMIN = en.pickBan.room.admin;
// The live match's seats, slot 1 bans first.
const SEATS = [
  { id: 71, slot: 1, name: "Bright Wolves" },
  { id: 72, slot: 2, name: "Quiet Foxes" },
];

const BAN: PickBanResolvedStep = {
  index: 0,
  round: 1,
  phase_id: "main",
  step_id: "s0",
  action: "ban",
  actors: [71],
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
};

function pool(): PickBanEntry[] {
  return [101, 102, 103].map((itemId, index) => ({
    id: 30 + index,
    item_id: itemId,
    round: 1,
    order: 0,
    action_index: null,
    picked_by_kind: null,
    picked_by_team_id: null,
    protected_by_kind: null,
    protected_by_team_id: null,
    status: "available",
    carried_from_round: null,
    picked_for_member_id: null,
  }));
}

/** The hero room as the host reads it: the first ban open (or held by a host), or the room after a host cancelled it. */
function heroState(status: "active" | "paused" | "cancelled"): PickBanState {
  const open = status !== "cancelled";
  return {
    session: {
      id: 1,
      kind: "hero",
      status: open ? "active" : "cancelled",
      first_team_id: 71,
      awaiting_choice: false,
      pending_chooser_team_id: null,
      seed_source: "bracket_slot",
      slot_reserves: null,
      started_at: "2026-10-22T20:00:00Z",
      current_step_started_at: null,
      paused_at: status === "paused" ? "2026-10-22T20:01:00Z" : null,
    },
    readiness: { 71: true, 72: true },
    sequence: [BAN],
    pool: pool(),
    submissions: [],
    viewer_team_id: null,
    viewer_can_act: false,
    allowed_actions: [],
    current_step_index: open ? 0 : null,
    current_step: open ? BAN : null,
    expected_action: null,
    acting_team_ids: open ? [71] : [],
    step_progress: null,
    step_deadline: null,
    current_round: 1,
    is_complete: false,
    eligible: null,
    draft_issues: [],
    targets: null,
    sides: [],
    dispute: { available: false, step_index: null, attempts_used: 0, max: 0 },
    undo: { requested_by_team_id: null, step_index: null, item_ids: [], action: null, encounter_team_id: null },
    members: [],
    acting_member_ids: [],
    viewer_member_ids: [],
    member_eligible: null,
  };
}

const MEMBERS = [
  { id: 501, encounter_team_id: 71, name: "P0" },
  { id: 502, encounter_team_id: 71, name: "P1" },
  { id: 601, encounter_team_id: 72, name: "P2" },
];

/** The room on one open step, everything about the current step overridden. */
function stepState(step: PickBanResolvedStep, overrides: Partial<PickBanState>): PickBanState {
  return {
    ...heroState("active"),
    sequence: [step],
    current_step: step,
    current_step_index: step.index,
    members: MEMBERS,
    ...overrides,
  };
}

/** P0's own pick: model (a), the next player of slot 1. */
const MEMBER_PICK: PickBanResolvedStep = {
  ...BAN,
  action: "pick",
  lifetime: null,
  member: "next",
  member_seats: [[71, 501]],
};
/** Model (b): every player of both teams picks at once. */
const EACH_PICK: PickBanResolvedStep = {
  ...MEMBER_PICK,
  actors: [71, 72],
  member: "each",
  member_seats: [
    [71, 501],
    [71, 502],
    [72, 601],
  ],
};
/** A free-order pick for slot 1: either of its players, the clock's stand-in P0. */
const FREE_PICK: PickBanResolvedStep = { ...MEMBER_PICK, member: "any" };
const ASSIGN: PickBanResolvedStep = { ...BAN, action: "assign", actors: [71, 72], lifetime: null, count: 2 };

/** The room once the step in play is answered by everyone: nothing left on the clock. */
function completed(state: PickBanState): PickBanState {
  return {
    ...state,
    is_complete: true,
    current_step: null,
    current_step_index: null,
    expected_action: null,
    acting_team_ids: [],
    viewer_can_act: false,
    allowed_actions: [],
  };
}

/** Each item's hero, picked by its player's team for that player. */
function owned(pool: PickBanEntry[], items: PickBanSubmissionItem[]): PickBanEntry[] {
  return pool.map((entry) => {
    const memberId = items.find((item) => item.item_id === entry.item_id)?.member_id;
    const member = MEMBERS.find((candidate) => candidate.id === memberId);
    return member == null
      ? entry
      : {
          ...entry,
          status: "picked",
          picked_by_kind: "team",
          picked_by_team_id: member.encounter_team_id,
          picked_for_member_id: member.id,
        };
  });
}

/** The server's answer to a member pick: the hero is that player's, and they owe nothing more. A pick naming no player
 * is refused, as the server refuses it. */
function afterPick(state: PickBanState, input: { item_id: number; member_id?: number | null }): PickBanState {
  const member = MEMBERS.find((candidate) => candidate.id === input.member_id);
  if (member == null || state.current_step_index == null) throw new Error("a member pick names its player");
  const acting = state.acting_member_ids.filter((id) => id !== member.id);
  const mine = state.viewer_member_ids.filter((id) => id !== member.id);
  const next: PickBanState = {
    ...state,
    pool: owned(state.pool, [{ item_id: input.item_id, target_player_id: null, member_id: member.id }]),
    submissions: [
      ...state.submissions,
      {
        step_index: state.current_step_index,
        encounter_team_id: member.encounter_team_id,
        team_member_id: member.id,
        attempt: 1,
        state: "locked",
        items: [{ item_id: input.item_id, target_player_id: null }],
      },
    ],
    acting_member_ids: acting,
    viewer_member_ids: mine,
    viewer_can_act: mine.length > 0,
    allowed_actions: mine.length > 0 ? ["pick"] : [],
  };
  return acting.length === 0 ? completed(next) : next;
}

/** The server's answer to a team's assignment, saved (unlocked) or locked: refused unless each hero goes to a player of
 * the team who may play it, once, and the rest of the team can still get one each -- all of them, on a lock. */
function afterAssign(state: PickBanState, teamId: number, input: PickBanSubmitInput): PickBanState {
  const players = MEMBERS.filter((member) => member.encounter_team_id === teamId);
  const extends_ = ([player, ...rest]: typeof players, taken: number[]): boolean =>
    player == null ||
    (state.member_eligible?.[String(player.id)] ?? []).some(
      (hero) =>
        (input.items.find((item) => item.member_id === player.id)?.item_id ?? hero) === hero &&
        !taken.includes(hero) &&
        extends_(rest, [...taken, hero]),
    );
  const step = state.current_step_index;
  if (step == null || !extends_(players, []) || (input.lock && input.items.length !== players.length))
    throw new Error("item_not_eligible");
  const submissions = [
    ...state.submissions.filter((row) => row.step_index !== step || row.encounter_team_id !== teamId),
    {
      step_index: step,
      encounter_team_id: teamId,
      team_member_id: null,
      attempt: 1,
      state: input.lock ? ("locked" as const) : ("draft" as const),
      items: input.items,
    },
  ];
  if (!input.lock) return { ...state, submissions };
  const acting = state.acting_team_ids.filter((id) => id !== teamId);
  const next: PickBanState = {
    ...state,
    pool: owned(state.pool, input.items),
    submissions,
    acting_team_ids: acting,
    viewer_can_act: false,
  };
  return acting.length === 0 ? completed(next) : next;
}

/** Serves `answer(state, input)` as the server's reply, and as every read after it; each write builds on the last.
 * With `hold`, a write lands (is applied and answered) only when the case says so, in the order it picks: a slow
 * network. */
function serve<I>(
  service: Mock,
  state: PickBanState,
  answer: (state: PickBanState, input: I) => PickBanState,
  hold = false,
) {
  let current = state;
  const held: (() => void)[] = [];
  getPickBanState.mockImplementation(async () => current);
  service.mockImplementation(
    (_kind: unknown, _encounterId: unknown, input: I) =>
      new Promise<PickBanState>((resolve, reject) => {
        const land = () => {
          try {
            current = answer(current, input);
            resolve(current);
          } catch (error) {
            reject(error);
          }
        };
        if (hold) held.push(land);
        else land();
      }),
  );
  return {
    server: () => current,
    pending: () => held.length,
    /** Lands one held write: the oldest, or the newest. */
    async land(newest = false) {
      await act(async () => (newest ? held.pop() : held.shift())?.());
      await settle();
    },
  };
}

/** Slot 1's captain on the assignment, each player offered the heroes `eligible` names. */
const assigning = (eligible: Record<string, number[]>) =>
  stepState(ASSIGN, {
    expected_action: "assign",
    viewer_team_id: 71,
    viewer_can_act: true,
    allowed_actions: ["assign"],
    acting_team_ids: [71],
    member_eligible: eligible,
  });

const tile = (name: string) => document.body.querySelector<HTMLButtonElement>(`[aria-label^="${name} — "]`);

let container: HTMLDivElement;
let root: Root;
let client: QueryClient;

beforeEach(() => {
  subscriptions.clear();
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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

/** The stage as the room mounts it: the room's hook reads the state, the stage renders it once it has a session. The
 * player a member pick is for comes from the room's rosters, here `chosenMember`. */
function Stage({
  canHost,
  showAdmin,
  chosenMember,
  onComplete
}: Readonly<{ canHost: boolean; showAdmin: boolean; chosenMember: number | null; onComplete: () => void }>) {
  const room = useMixBanRoom(50, "overwatch");
  if (room.state?.session == null) return null;
  return (
    <RoomBanStage
      encounterId={50}
      workspaceId={7}
      discipline="overwatch"
      seats={SEATS}
      state={{ ...room.state, session: room.state.session }}
      queryKey={room.queryKey}
      heroesById={room.heroesById}
      canHost={canHost}
      showAdmin={showAdmin}
      chosenMember={chosenMember}
      onComplete={onComplete}
    />
  );
}

async function render(
  onComplete: () => void,
  canHost = true,
  showAdmin = canHost,
  chosenMember: number | null = null,
) {
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en} timeZone="UTC">
          <Stage canHost={canHost} showAdmin={showAdmin} chosenMember={chosenMember} onComplete={onComplete} />
        </NextIntlClientProvider>
      </QueryClientProvider>,
    );
  });
  await settle();
}

const byLabel = (label: string) =>
  [...document.body.querySelectorAll("button")].find((button) => button.textContent?.trim() === label) ?? null;

const give = (hero: string, player: string) =>
  document.body.querySelector<HTMLButtonElement>(`[aria-label="Give ${hero} to ${player}"]`);

/** Past the board's ~300ms draft-save debounce, then let the response land. */
async function debounce() {
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 400);
    await promise;
  });
  await settle();
}

describe("RoomBanStage", () => {
  it("re-reads the lobby once when a host cancels the ban room", async () => {
    let refreshes = 0;
    getPickBanState.mockResolvedValue(heroState("active"));
    await render(() => (refreshes += 1));

    expect(container.textContent).toContain(en.mixes.room.bansTitle);
    expect(refreshes).toBe(0);

    await act(async () => byLabel(ADMIN.cancelSession)?.click());
    await settle();
    const reason = document.body.querySelector<HTMLInputElement>(`input[aria-label="${ADMIN.cancelReason}"]`);
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(reason, "voice is down");
      reason?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    // The server cancels the room; the board's next read says so.
    adminPickBanCancel.mockImplementation(async () => {
      getPickBanState.mockResolvedValue(heroState("cancelled"));
      return {};
    });
    await act(async () => byLabel(ADMIN.cancelConfirmAction)?.click());
    await settle();

    expect(adminPickBanCancel).toHaveBeenCalledTimes(1);
    expect(byLabel(ADMIN.cancelSession)).toBeNull();
    expect(refreshes).toBe(1);

    // The room re-renders while its lobby reloads, with a new callback each time: still one refresh.
    await render(() => (refreshes += 1));
    expect(refreshes).toBe(1);
  });

  it("catches up on a resume made before its live subscription landed", async () => {
    // The first read finds the room held; a host resumes it before this page subscribes, and a fresh topic replays
    // nothing -- so the board must re-read on the subscription itself.
    getPickBanState.mockResolvedValue(heroState("paused"));
    await render(() => {});
    expect(document.body.textContent).toContain(en.pickBan.room.pausedBanner);

    getPickBanState.mockResolvedValue(heroState("active"));
    await act(async () => subscriptions.get("encounter:50:pick-ban:hero")?.onSubscribed?.());
    await settle();

    expect(document.body.textContent).not.toContain(en.pickBan.room.pausedBanner);
  });

  it("names the player on their pick and picks the hero for them", async () => {
    serve(
      performPickBanAction,
      stepState(MEMBER_PICK, {
        expected_action: "pick",
        viewer_can_act: true,
        allowed_actions: ["pick"],
        acting_member_ids: [501],
        viewer_member_ids: [501],
        member_eligible: { "501": [101, 102, 103] },
      }),
      afterPick,
    );
    await render(() => {});

    expect(container.textContent).toContain("Picking: P0");
    await act(async () => tile("Hero 101")?.click());
    await act(async () => byLabel("Pick Hero 101 for P0")?.click());
    await settle();

    // Hero 101 is P0's now: out of the pool, and the room is done.
    expect(tile("Hero 101")?.getAttribute("aria-label")).toBe(`Hero 101 — ${en.pickBan.room.status.picked}`);
    expect(container.textContent).toContain(en.pickBan.room.completedBanner);
  });

  it("lets a captain pick for a teammate once another teammate has locked", async () => {
    // P0, the captain, already took Hero 101; P1 and the other team's P2 still owe.
    const open = stepState(EACH_PICK, {
      expected_action: "pick",
      viewer_team_id: 71,
      viewer_can_act: true,
      allowed_actions: ["pick"],
      acting_team_ids: [71, 72],
      acting_member_ids: [501, 502, 601],
      viewer_member_ids: [501, 502],
      member_eligible: { "501": [101, 102, 103], "502": [102, 103], "601": [102, 103] },
    });
    serve(performPickBanAction, afterPick(open, { item_id: 101, member_id: 501 }), afterPick);
    await render(() => {}, false);

    const step = container.querySelector(`ol[aria-label="${en.mixes.arena.bans.steps}"] li[aria-current="step"]`);
    expect(step?.textContent).toContain(en.mixes.arena.bans.everyone);
    await act(async () => tile("Hero 102")?.click());
    await act(async () => byLabel("Pick Hero 102 for P1")?.click());
    await settle();

    // P1 has Hero 102; only P2 still picks, and nothing is left for this captain.
    expect(tile("Hero 102")?.getAttribute("aria-label")).toBe(`Hero 102 — ${en.pickBan.room.status.picked}`);
    expect(container.textContent).toContain("Picking: P2");
    expect(container.textContent).not.toContain("Pick Hero");
  });

  it("drops a chosen hero when the captain switches to a player who may not take it", async () => {
    // Fearless: P1 already played Hero 101, so only P0 may take it.
    getPickBanState.mockResolvedValue(
      stepState(EACH_PICK, {
        expected_action: "pick",
        viewer_team_id: 71,
        viewer_can_act: true,
        allowed_actions: ["pick"],
        acting_team_ids: [71, 72],
        acting_member_ids: [501, 502, 601],
        viewer_member_ids: [501, 502],
        member_eligible: { "501": [101, 102, 103], "502": [102, 103], "601": [101, 102, 103] },
      }),
    );
    await render(() => {}, false);

    await act(async () => tile("Hero 101")?.click());
    expect(byLabel("Pick Hero 101 for P0")?.disabled).toBe(false);
    // The captain chooses P1 on the roster.
    await render(() => {}, false, false, 502);

    const confirmations = [...document.body.querySelectorAll("button")].filter(
      (button) => button.textContent?.trim().startsWith("Pick ") && !button.disabled,
    );
    expect(confirmations).toEqual([]);
  });

  it("waits on a free-order pick for the player tapped, then picks the hero for them", async () => {
    serve(
      performPickBanAction,
      stepState(FREE_PICK, {
        expected_action: "pick",
        viewer_team_id: 71,
        viewer_can_act: true,
        allowed_actions: ["pick"],
        acting_member_ids: [501, 502],
        viewer_member_ids: [501, 502],
        member_eligible: { "501": [101, 102], "502": [101, 102] },
      }),
      afterPick,
    );
    await render(() => {}, false);

    // Nobody is chosen yet: no hero to confirm, and the bar says why.
    await act(async () => tile("Hero 101")?.click());
    expect(byLabel("Pick Hero 101 for P0")).toBeNull();
    expect(container.textContent).toContain(en.mixes.arena.bans.choosePlayer);
    expect(container.textContent).not.toContain("Picking:");

    // The captain taps P1 on the roster.
    await render(() => {}, false, false, 502);
    await act(async () => tile("Hero 101")?.click());
    await act(async () => byLabel("Pick Hero 101 for P1")?.click());
    await settle();

    expect(performPickBanAction).toHaveBeenCalledWith("hero", 50, { item_id: 101, action: "pick", member_id: 502 });
  });

  it("tells a player on a captains-only pick that the captains pick", async () => {
    getPickBanState.mockResolvedValue(
      stepState(
        { ...EACH_PICK, captains_only: true },
        {
          expected_action: "pick",
          acting_team_ids: [71, 72],
          acting_member_ids: [501, 502, 601],
          member_eligible: { "501": [101], "502": [101], "601": [101] },
        },
      ),
    );
    await render(() => {}, false);

    expect(container.textContent).toContain(en.mixes.arena.bans.captainsPick);
  });

  it("alerts a player on each of their picks with the pick title", async () => {
    const vibrate = vi.fn();
    Object.defineProperty(navigator, "vibrate", { value: vibrate, configurable: true });
    const second: PickBanResolvedStep = { ...MEMBER_PICK, index: 1, step_id: "s1", member_seats: [[71, 502]] };
    const turn = (step: PickBanResolvedStep, member: number): PickBanState => ({
      ...stepState(step, {
        expected_action: "pick",
        viewer_team_id: 71,
        viewer_can_act: true,
        allowed_actions: ["pick"],
        acting_member_ids: [member],
        viewer_member_ids: [member],
        member_eligible: { [String(member)]: [101, 102] },
      }),
      sequence: [MEMBER_PICK, second],
    });
    getPickBanState.mockResolvedValue(turn(MEMBER_PICK, 501));
    await render(() => {});

    expect(document.title).toBe(en.mixes.room.yourPickTitle);
    expect(vibrate).toHaveBeenLastCalledWith(200);

    // The captain's next pick, for a teammate, right after: the same team on the clock, a new turn.
    getPickBanState.mockResolvedValue(turn(second, 502));
    await act(async () => subscriptions.get("encounter:50:pick-ban:hero")?.onEvent());
    await settle();

    expect(document.title).toBe(en.mixes.room.yourPickTitle);
    // One buzz per turn: the first one's was stopped when it passed.
    expect(vibrate.mock.calls.filter(([ms]) => ms === 200)).toHaveLength(2);
  });

  it("saves a captain's assignment as they make it, so a refresh keeps it, and locks it", async () => {
    let refreshes = 0;
    serve(submitDraft, assigning({ "501": [101, 102], "502": [101, 102] }), (state, input: PickBanSubmitInput) =>
      afterAssign(state, 71, input),
    );
    await render(() => (refreshes += 1));

    await act(async () => give("Hero 101", "P0")?.click());
    await debounce();

    // A fresh page reads the choice back from the server: saved, and still the captain's to change.
    act(() => root.unmount());
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    root = createRoot(container);
    await render(() => (refreshes += 1));
    expect(give("Hero 101", "P0")?.getAttribute("aria-pressed")).toBe("true");
    expect(give("Hero 101", "P1")?.getAttribute("aria-pressed")).toBe("false");
    expect(give("Hero 102", "P1")?.disabled).toBe(false);
    // Not lockable until every player has a hero.
    expect(byLabel(en.pickBan.room.assign.lock)?.disabled).toBe(true);

    await act(async () => give("Hero 102", "P1")?.click());
    expect(byLabel(en.pickBan.room.assign.lock)?.disabled).toBe(false);
    await act(async () => byLabel(en.pickBan.room.assign.lock)?.click());
    await settle();

    // Both heroes went out, the room is done, and the lobby re-reads once.
    expect(byLabel(en.pickBan.room.assign.lock)).toBeNull();
    expect(tile("Hero 101")?.getAttribute("aria-label")).toBe(`Hero 101 — ${en.pickBan.room.status.picked}`);
    expect(tile("Hero 102")?.getAttribute("aria-label")).toBe(`Hero 102 — ${en.pickBan.room.status.picked}`);
    expect(refreshes).toBe(1);
  });

  it("keeps the saved assignment when the server refuses a choice that leaves a player without a hero", async () => {
    // P1 may play only Hero 101: giving it to P0 leaves P1 nothing.
    serve(submitDraft, assigning({ "501": [101, 102], "502": [101] }), (state, input: PickBanSubmitInput) =>
      afterAssign(state, 71, input),
    );
    await render(() => {});

    await act(async () => give("Hero 101", "P0")?.click());
    await debounce();

    expect(notify.apiError).toHaveBeenCalledTimes(1);
    expect(give("Hero 101", "P0")?.getAttribute("aria-pressed")).toBe("false");
  });

  it("saves a team's assignment in order, so a slow save never lands over a newer one", async () => {
    const room = serve(
      submitDraft,
      assigning({ "501": [101, 102], "502": [101, 102] }),
      (state, input: PickBanSubmitInput) => afterAssign(state, 71, input),
      true,
    );
    await render(() => {});

    await act(async () => give("Hero 101", "P0")?.click());
    await debounce();
    await act(async () => give("Hero 102", "P0")?.click());
    await debounce();
    // The network lands whatever is in flight newest first.
    while (room.pending() > 0) await room.land(true);

    const row = room.server().submissions.find((submission) => submission.encounter_team_id === 71);
    expect(row?.items.map((item) => [item.member_id, item.item_id])).toEqual([[501, 102]]);
  });

  it("keeps a correction made while the server was refusing the choice it replaced", async () => {
    // P1 may play only Hero 101: giving it to P0 is refused; giving P0 Hero 102 instead is fine.
    const room = serve(
      submitDraft,
      assigning({ "501": [101, 102], "502": [101] }),
      (state, input: PickBanSubmitInput) => afterAssign(state, 71, input),
      true,
    );
    await render(() => {});

    await act(async () => give("Hero 101", "P0")?.click());
    await debounce();
    await act(async () => give("Hero 102", "P0")?.click());
    await debounce();
    await room.land(); // the refusal

    expect(give("Hero 102", "P0")?.getAttribute("aria-pressed")).toBe("true");
    while (room.pending() > 0) await room.land();
    expect(give("Hero 102", "P0")?.getAttribute("aria-pressed")).toBe("true");
    const row = room.server().submissions.find((submission) => submission.encounter_team_id === 71);
    expect(row?.items.map((item) => [item.member_id, item.item_id])).toEqual([[501, 102]]);
  });

  it("locks at once while an earlier save never settles", async () => {
    const room = serve(
      submitDraft,
      assigning({ "501": [101, 102], "502": [101, 102] }),
      (state, input: PickBanSubmitInput) => afterAssign(state, 71, input),
      true,
    );
    await render(() => {});

    await act(async () => give("Hero 101", "P0")?.click());
    await debounce(); // this save is stuck for good
    await act(async () => give("Hero 102", "P1")?.click());
    await act(async () => byLabel(en.pickBan.room.assign.lock)?.click());
    await room.land(true);

    expect(byLabel(en.pickBan.room.assign.lock)).toBeNull();
    expect(container.textContent).toContain(en.pickBan.room.completedBanner);
    const row = room.server().submissions.find((submission) => submission.encounter_team_id === 71);
    expect(row?.state).toBe("locked");
    expect(row?.items.map((item) => [item.member_id, item.item_id])).toEqual([
      [501, 101],
      [502, 102],
    ]);
  });

  it("sends nothing it still had queued once the board is closed", async () => {
    const room = serve(
      submitDraft,
      assigning({ "501": [101, 102], "502": [101, 102] }),
      (state, input: PickBanSubmitInput) => afterAssign(state, 71, input),
      true,
    );
    await render(() => {});

    await act(async () => give("Hero 101", "P0")?.click());
    await debounce(); // on the wire
    await act(async () => give("Hero 102", "P0")?.click());
    await debounce(); // queued behind it
    act(() => root.unmount());
    root = createRoot(container);
    await room.land();

    // Only the save already on the wire landed; the queued one never went out.
    expect(room.pending()).toBe(0);
    const row = room.server().submissions.find((submission) => submission.encounter_team_id === 71);
    expect(row?.items.map((item) => [item.member_id, item.item_id])).toEqual([[501, 101]]);
  });

  it("holds the board still while its Lock is in flight", async () => {
    serve(
      submitDraft,
      assigning({ "501": [101, 102], "502": [101, 102] }),
      (state, input: PickBanSubmitInput) => afterAssign(state, 71, input),
      true,
    );
    await render(() => {});

    await act(async () => give("Hero 101", "P0")?.click());
    await act(async () => give("Hero 102", "P1")?.click());
    await act(async () => byLabel(en.pickBan.room.assign.lock)?.click());
    await settle();

    const heroes = [...document.body.querySelectorAll<HTMLButtonElement>('[aria-label^="Give Hero"]')];
    expect(heroes).toHaveLength(4);
    expect(heroes.every((button) => button.disabled)).toBe(true);
  });

  it("lets a host ban for the team on the clock from the bar", async () => {
    // Slot 1's captain is away: the host, no captain of either team, answers its open ban.
    getPickBanState.mockResolvedValue(heroState("active"));
    adminPickBanAct.mockResolvedValue({});
    await render(() => {}, true, false);

    await act(async () => tile("Hero 101")?.click());
    await act(async () => byLabel("Ban Hero 101")?.click());
    await settle();

    expect(adminPickBanAct).toHaveBeenCalledWith(50, {
      kind: "hero",
      encounter_team_id: 71,
      item_id: 101,
      action: "ban",
    });
  });

  it("offers a spectator no answer to the step in play", async () => {
    getPickBanState.mockResolvedValue(heroState("active"));
    await render(() => {}, false);

    await act(async () => tile("Hero 101")?.click());

    expect(byLabel("Ban Hero 101")).toBeNull();
    expect(adminPickBanAct).not.toHaveBeenCalled();
  });
});
