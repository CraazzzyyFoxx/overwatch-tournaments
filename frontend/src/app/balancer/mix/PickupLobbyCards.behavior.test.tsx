// @vitest-environment happy-dom
//
// The overview of a mix running several lobbies (spec §7.5, A1). Pinned:
//  1. a one-lobby mix has no cards -- the overview is its desk;
//  2. each card carries the one action its stage calls for, for its own lobby: Balance, Start match, Record;
//  3. Balance is off, with the reason, while the lobby cannot fill its seats;
//  4. a viewer gets every lobby's stage and the way into its room, and no action;
//  5. Shuffle all lobbies goes straight through over recorded lineups, and asks first while any lobby's lineup is
//     unrecorded;
//  6. beside the cards, who waits for a seat, who is away and who sits on the bench, each in its own group;
//  7. in draft mode an idle card drafts (the balancer one menu away), Split pool replaces Shuffle all, and a drafting
//     card reads its stage and, once the draft runs, its elapsed time;
//  8. a card's room link is the loud one while its draft or bans play out there, and its Teams toggle picks the desk
//     shown under the cards.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGame, CustomGameLobby, CustomGamePlayer } from "@/services/custom-game.service";

import { PickupLobbyCards } from "./PickupLobbyCards";
import { OW_OWNER } from "./mix-owner.fixture";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

vi.mock("next-intl", () => ({
  useTranslations: () =>
    Object.assign(
      (key: string, values?: Record<string, unknown>) =>
        values ? `${key}:${Object.values(values).join(",")}` : key,
      { has: () => false },
    ),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
// The groups reuse the lineup's own rows, which are drag sources; dnd-kit resolves its own React copy under pnpm
// (see PickupLobbyPanel.behavior.test.tsx), so it renders inertly here.
vi.mock("@dnd-kit/core", () => ({
  useDraggable: () => ({ attributes: {}, listeners: {}, setNodeRef: () => {}, isDragging: false }),
}));

const onBalance = vi.fn();
const onStartMatch = vi.fn();
const onRecordOutcome = vi.fn();
const onShuffleAll = vi.fn();
const onDraft = vi.fn();
const onSplitPool = vi.fn();
const onSelectLobby = vi.fn();

function lobby(index: number, overrides: Partial<CustomGameLobby> = {}): CustomGameLobby {
  return {
    lobby_index: index,
    balance_result: null,
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: null,
    team1_voice_channel_id: null,
    team2_voice_channel_id: null,
    live_encounter_id: null,
    state: "idle",
    live_started_at: null,
    lineup_recorded: true,
    matches_count: 0,
    ...overrides,
  };
}

function player(memberId: number, overrides: Partial<CustomGamePlayer> = {}): CustomGamePlayer {
  return {
    id: memberId,
    workspace_member_id: memberId,
    display_name: `P${memberId}`,
    display: { name: `P${memberId}`, tag: null, canonical: null, snapshot: null },
    identity: null,
    sort_order: memberId,
    participation: "pool",
    role_selection_mode: "all_ranked",
    is_flex: false,
    away: false,
    current_lobby: null,
    lobby_pin: null,
    roles: null,
    ranks: {},
    rank_sources: {},
    author_ranks: {},
    ...overrides,
  };
}

function game(lobbies: CustomGameLobby[]): CustomGame {
  return {
    id: 3,
    workspace_id: 7,
    discipline: "overwatch",
    host_user_id: 9,
    co_hosts: [],
    host_display_name: null,
    name: "Thursday scrim",
    status: "balanced",
    settings: { points_per_win: 0, team_names: {}, workspace_discord_channel_id: null },
    created_at: null,
    lobby_count: lobbies.length,
    lobbies,
    roster_shape: null,
    matches_count: 0,
    last_match_at: null,
    self_signup: "closed",
    self_role_edit: false,
    general_voice_channel_id: null,
    players: [],
    team_formation: "balance",
    draft_pick_seconds: 30,
  };
}

/** A full lobby's worth of waiting players (Overwatch 5v5). */
const TEN = Array.from({ length: 10 }, (_, index) => player(index + 1));

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(
  current: CustomGame,
  {
    rows = TEN,
    canWrite = true,
    selectedLobby = null,
  }: { rows?: CustomGamePlayer[]; canWrite?: boolean; selectedLobby?: number | null } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupLobbyCards
        game={current}
        rows={rows}
        owner={OW_OWNER}
        canWrite={canWrite}
        balancingLobby={null}
        startingLobby={null}
        recordingLobby={null}
        shufflingAll={false}
        onBalance={onBalance}
        onStartMatch={onStartMatch}
        onRecordOutcome={onRecordOutcome}
        onShuffleAll={onShuffleAll}
        drafting={null}
        onDraft={onDraft}
        splitting={false}
        onSplitPool={onSplitPool}
        selectedLobby={selectedLobby}
        onSelectLobby={onSelectLobby}
      />,
    );
  });
  await act(async () => {
    await tick();
  });
  return container;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function byName(scope: ParentNode, name: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null;
}

/** The players one named group lists, in its order (each row's text opens with the player's name). */
function group(scope: ParentNode, name: string) {
  const section = scope.querySelector(`section[aria-label="${name}"]`);
  if (!section) throw new Error(`Expected a group named ${name}`);
  return [...section.querySelectorAll("li")].map((row) => /^P\d+/.exec(row.textContent ?? "")?.[0]);
}

beforeEach(() => {
  document.body.innerHTML = "";
  for (const fn of [onBalance, onStartMatch, onRecordOutcome, onShuffleAll, onDraft, onSplitPool, onSelectLobby]) {
    fn.mockReset();
  }
});

describe("PickupLobbyCards", () => {
  it("renders nothing for a mix that runs one lobby: the overview is its desk", async () => {
    const scope = await mount(game([lobby(0)]));

    expect(scope.textContent).toBe("");
  });

  it("gives each lobby the one action its stage calls for", async () => {
    const scope = await mount(
      game([lobby(0), lobby(1, { state: "ready" }), lobby(2, { state: "live", live_encounter_id: 50 })]),
    );

    await click(byName(scope, "balance"));
    expect(onBalance).toHaveBeenCalledWith(0);
    await click(byName(scope, "startMatch"));
    expect(onStartMatch).toHaveBeenCalledWith(1, false);

    await click(byName(scope, "record"));
    const items = [...document.querySelectorAll('[role="menuitem"]')];
    expect(items.map((item) => item.textContent)).toEqual(["teamWin:team:1", "draw", "teamWin:team:2"]);
    await click(items[1]);
    expect(onRecordOutcome).toHaveBeenCalledWith({ outcome: { winner: null }, lobbyIndex: 2 });
  });

  it("names who bans first before a card starts its match, and starts it with the host's swap", async () => {
    const scope = await mount(game([lobby(0), lobby(1, { state: "ready", opener_index: 1 })]));

    await click(byName(scope, "startMatch"));
    expect(onStartMatch).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("opener:team:2");

    await click(document.querySelector('[role="switch"]'));
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("opener:team:1");
    await click(byName(document, "startConfirm"));

    expect(onStartMatch).toHaveBeenCalledWith(1, true);
  });

  it("times a lobby's Pre-game the way it times a live match, with no result to record yet", async () => {
    // On a minute boundary, so the card's minute clock reads exactly twelve.
    const startedAt = new Date(Math.floor(Date.now() / 60_000) * 60_000 - 12 * 60_000).toISOString();
    const scope = await mount(
      game([lobby(0), lobby(1, { state: "pregame", live_encounter_id: 50, live_started_at: startedAt })]),
    );

    expect(scope.textContent).toContain("state.pregame");
    expect(scope.textContent).toContain("elapsed:12");
    expect(byName(scope, "record")).toBeNull();
    expect(byName(scope, "startMatch")).toBeNull();
    expect([...scope.querySelectorAll("a")].map((link) => link.getAttribute("href"))).toContain(
      "/balancer/mix/3/lobby/B",
    );
    expect(scope.querySelector('a[href="/balancer/mix/3/lobby/B"]')?.className).toContain("--color-primary");
  });

  it("keeps Balance off, with the reason, while the lobby cannot fill its seats", async () => {
    const scope = await mount(game([lobby(0), lobby(1)]), { rows: TEN.slice(0, 4) });

    expect(byName(scope, "balance")?.hasAttribute("disabled")).toBe(true);
    expect(scope.textContent).toContain("shortSeats:4,10");
  });

  it("shows a viewer every lobby's stage and the way into its room, and no action", async () => {
    const scope = await mount(
      game([lobby(0, { state: "ready" }), lobby(1, { state: "live", live_encounter_id: 50 })]),
      { canWrite: false },
    );

    expect(byName(scope, "startMatch")).toBeNull();
    expect(byName(scope, "record")).toBeNull();
    expect(byName(scope, "shuffleAll")).toBeNull();
    expect(scope.textContent).toContain("state.ready");
    expect(scope.textContent).toContain("state.live");
    expect([...scope.querySelectorAll("a")].map((link) => link.getAttribute("href"))).toEqual([
      "/balancer/mix/3/lobby/A",
      "/balancer/mix/3/lobby/B",
    ]);
  });

  it("shuffles every lobby straight away while each lineup on screen is recorded", async () => {
    const scope = await mount(game([lobby(0, { state: "ready" }), lobby(1, { state: "ready" })]));

    await click(byName(scope, "shuffleAll"));

    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    expect(onShuffleAll).toHaveBeenCalledTimes(1);
  });

  it("shuffles every lobby only after confirming over a lineup nobody recorded, in any lobby", async () => {
    const scope = await mount(game([lobby(0, { state: "ready" }), lobby(1, { state: "ready", lineup_recorded: false })]));

    await click(byName(scope, "shuffleAll"));
    expect(onShuffleAll).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("shuffleDescription");
    await click(byName(document, "shuffleConfirm"));

    expect(onShuffleAll).toHaveBeenCalledTimes(1);
  });

  it("drafts an idle lobby of a draft-mode mix and keeps the balancer one menu away", async () => {
    const scope = await mount({ ...game([lobby(0, { state: "idle" }), lobby(1, { state: "idle" })]), team_formation: "draft" });
    const [firstCard] = scope.querySelectorAll("li");

    await click(byName(firstCard, "draft"));

    expect(onDraft).toHaveBeenCalledWith(0);
    expect(byName(firstCard, "balance")).toBeNull();
    expect(firstCard.querySelector('button[aria-haspopup="menu"]')).not.toBeNull();
  });

  it("splits the pool instead of shuffling all lobbies in draft mode", async () => {
    const scope = await mount({ ...game([lobby(0, { state: "ready" }), lobby(1, { state: "ready" })]), team_formation: "draft" });

    expect(byName(scope, "shuffleAll")).toBeNull();
    await click(byName(scope, "splitPool"));

    expect(onSplitPool).toHaveBeenCalledTimes(1);
  });

  it("times a running draft from its first pick, and never reads a drafting lobby as short of seats", async () => {
    // On a minute boundary, so the card's minute clock reads exactly seven.
    const startedAt = new Date(Math.floor(Date.now() / 60_000) * 60_000 - 7 * 60_000).toISOString();
    const scope = await mount(
      {
        ...game([lobby(0, { state: "draft_setup" }), lobby(1, { state: "draft_live", live_started_at: startedAt })]),
        team_formation: "draft",
      },
      { rows: TEN.slice(0, 4) },
    );
    const [setup, live] = scope.querySelectorAll("li");

    expect(setup.textContent).toContain("state.draft_setup");
    expect(live.textContent).toContain("state.draft_live");
    expect(live.textContent).toContain("elapsed:7");
    expect(scope.textContent).not.toContain("shortSeats");
  });

  it("makes the room link the loud one while a lobby's draft or bans play out there", async () => {
    const scope = await mount(
      game([
        lobby(0, { state: "ready" }),
        lobby(1, { state: "draft_setup", draft_session_id: 77 }),
        lobby(2, { state: "pregame", live_encounter_id: 50 }),
        lobby(3, { state: "live", live_encounter_id: 51 }),
      ]),
      { canWrite: false },
    );
    const loud = [...scope.querySelectorAll("a")].map((link) => link.className.includes("--color-primary"));

    expect(loud).toEqual([false, true, true, false]);
  });

  it("opens a lobby's desk from its card and closes it from the same toggle", async () => {
    const scope = await mount(game([lobby(0), lobby(1)]));
    const [, second] = scope.querySelectorAll("li");

    expect(byName(second, "desk")?.getAttribute("aria-pressed")).toBe("false");
    await click(byName(second, "desk"));
    expect(onSelectLobby).toHaveBeenLastCalledWith(1);

    const picked = await mount(game([lobby(0), lobby(1)]), { selectedLobby: 1 });
    const [first, selected] = picked.querySelectorAll("li");

    expect(byName(selected, "desk")?.getAttribute("aria-pressed")).toBe("true");
    expect(selected.className).toContain("border-[color:var(--aqt-teal)]");
    expect(first.className).not.toContain("border-[color:var(--aqt-teal)]");
    await click(byName(selected, "desk"));
    expect(onSelectLobby).toHaveBeenLastCalledWith(null);
  });

  it("lists who waits for a seat, who is away and who sits on the bench", async () => {
    const scope = await mount(game([lobby(0, { state: "ready" }), lobby(1, { state: "ready" })]), {
      rows: [
        player(1),
        player(2, { participation: "must_play" }),
        player(3, { current_lobby: 0 }),
        player(4, { away: true, current_lobby: 1 }),
        player(5, { participation: "benched" }),
        player(6, { participation: "benched", away: true }),
      ],
      canWrite: false,
    });

    expect(group(scope, "groups.waiting")).toEqual(["P1", "P2"]);
    expect(group(scope, "groups.away")).toEqual(["P4", "P6"]);
    expect(group(scope, "groups.bench")).toEqual(["P5"]);
  });
});
