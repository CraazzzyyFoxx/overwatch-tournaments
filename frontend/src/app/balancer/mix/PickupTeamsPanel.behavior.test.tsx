// @vitest-environment happy-dom
//
// The teams column replaced a `<pre>{JSON.stringify(balance_result)}</pre>`, so
// what is pinned here is that it actually reads the payload, and that the two
// writes it owns cannot fire by accident:
//
//  1. seats render per team with the rating the solver assigned, not raw JSON;
//  2. the solver returns many equally-scored options and the pager walks them
//     without re-running the balance — the index is owned by the page, so the
//     panel reports the move instead of keeping its own copy;
//  3. the index is clamped, so a shorter result cannot point past the end;
//  4. Balance is refused while nobody is checked in the lineup, which is the
//     `empty_lineup` 422 the server would raise;
//  5. recording a result is a deliberate click on a live match, repeatable,
//     and names its lobby; closing the mix is a separate, explicit action;
//  6. a read-only viewer gets no writes but still sees teams;
//  7. the verdict pills sit inside the captured block with the team card, so
//     "Copy image" exports them together, while "Copy image"/"Copy handles"
//     stay outside it -- exporting its own toolbar would be a screenshot of a
//     screenshot button;
//  8. every seat is a drag source and drop target, gated on both write access
//     and the page actually offering a swap handler -- a read-only viewer or
//     a page with nothing to call must not present drag affordance for a
//     write that cannot happen;
//  9. only the newest recorded match offers an undo, and only to a writer the
//     page actually handed a handler -- an older one would have to unwind
//     every match stacked on top of it;
// 10. Post to Discord appears only for a writer whose mix has a channel
//     configured, and posts the option the pager is on, not always the first;
// 11. a lobby walks Ready -> Live: Start match opens it (asking first while an
//     away player is still seated), a live lineup is frozen to its result and
//     Cancel match, and each team's captain wears the crown;
// 12. what plays out in the lobby's room is a link there, never a board: a drafting lobby's desk is one card pointing
//     at its room, Pre-game and Live keep the frozen lineup with an Open room link (the loud one while the bans
//     run), and each recorded round lists its bans.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { CustomGame, CustomGameLobby, CustomGameMatch, CustomGamePlayer } from "@/services/custom-game.service";
import { catalogMap, catalogMode } from "@/test/catalog";
import type { CatalogEntityRead } from "@/types/catalog.types";

import { PickupTeamsPanel } from "./PickupTeamsPanel";
import { mixRoomHref } from "./pickup-chrome";
import { DEADLOCK_OWNER, LOL_OWNER, OW_OWNER } from "./mix-owner.fixture";
import type { MixOwner } from "./pickup-lineup";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;


vi.mock("@/lib/datetime/client", () => ({ useFormatter: () => ({ relativeTime: () => "just now" }) }));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));
// Drag itself is not what this pins, and dnd-kit resolves its own React copy
// under pnpm (see PickupPlayerSheet.behavior.test.tsx), so it renders inertly
// here: children mount as plain DOM, no real drag/drop wiring.
const dndSpies = vi.hoisted(() => ({
  useDraggable: vi.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: () => {},
    transform: null,
    isDragging: false,
  })),
  useDroppable: vi.fn(() => ({ setNodeRef: () => {}, isOver: false })),
}));
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({ children }: { children: React.ReactNode }) => children,
  DragOverlay: () => null,
  PointerSensor: class {},
  KeyboardSensor: class {},
  useSensor: () => null,
  useSensors: () => [],
  useDraggable: dndSpies.useDraggable,
  useDroppable: dndSpies.useDroppable,
}));
// The rasteriser is the export pipeline's, not this panel's.
const captureSpies = vi.hoisted(() => ({ capture: vi.fn(), capturing: false }));
vi.mock("@/hooks/useNodeCapture", () => ({
  useNodeCapture: () => ({
    ref: { current: null },
    capturing: captureSpies.capturing,
    capture: captureSpies.capture,
  }),
}));
// The history's ban strip names its heroes from the game's catalog (the fields it reads).
vi.mock("@/services/catalog.service", () => ({
  default: {
    list: async () => ({
      results: [
        { id: 101, name: "Ana", image_path: null },
        { id: 102, name: "Genji", image_path: null },
      ],
    }),
  },
}));

const onBalance = vi.fn();
const onVariantIndexChange = vi.fn();
const onRecordOutcome = vi.fn();
const onNextMapChange = vi.fn();
const onCloseMix = vi.fn();
const onCopyHandles = vi.fn();
const onRenameTeam = vi.fn();
const onSwapSeats = vi.fn();
const onUndoMatch = vi.fn();
const onPostToDiscord = vi.fn();
const onStartMatch = vi.fn();
const onCancelMatch = vi.fn();
const onMakeCaptain = vi.fn();

// One lobby, rated once: an option only says who sits where.
const PLAYERS = {
  "7": { name: "karin", ratings: { Tank: 2900, Damage: 3100 }, role_preferences: ["Tank"] },
  "8": { name: "DemonDimon", ratings: { Tank: 3900, Damage: 4100 }, role_preferences: ["Tank", "Damage"] },
  "9": { name: "Tolgrn", ratings: { Support: 3450 } },
  "10": { name: "Egor" },
};

function variant(offset: number, [tank, damage]: [string, string] = ["7", "8"]) {
  return {
    teams: [
      { id: 1, average_mmr: 3000 + offset, roster: { Tank: [tank], Damage: [damage] } },
      { id: 2, average_mmr: 2950, roster: { Support: ["9"] } },
    ],
    statistics: { composite_score: 0.87, mmr_std_dev: 12.34, off_role_count: 1 } as Record<string, unknown>,
    benched: ["10"],
  };
}

function lobby(variants: unknown[], feasibility: unknown = null) {
  return { players: PLAYERS, feasibility, variants };
}

const SETTINGS = {
  points_per_win: 0,
  team_names: {},
  workspace_discord_channel_id: null,
};

const CONTROL = catalogMode(1, "Control");
const HYBRID = catalogMode(2, "Hybrid");

const CATALOGUE = [
  catalogMap(5, HYBRID, { name: "King's Row" }),
  catalogMap(6, CONTROL, { name: "Ilios" }),
  catalogMap(7, CONTROL, { name: "Busan" })
];

/** One row of the mix's `lobbies[]` — the four columns that moved off `custom_game`. */
function lobbyRow(overrides: Partial<CustomGameLobby> = {}): CustomGameLobby {
  return {
    lobby_index: 0,
    // The last option seats karin at damage, where she is rated 3100.
    balance_result: lobby([variant(0), variant(100), variant(200, ["8", "7"])]),
    selected_variant_index: 0,
    next_map_id: null,
    balanced_at: "2026-01-01T00:00:00Z",
    lineup_recorded: true,
    matches_count: 0,
    live_encounter_id: null,
    state: "ready",
    live_started_at: null,
    ...overrides,
  };
}

function game(overrides: Partial<CustomGame> = {}): CustomGame {
  return {
    id: 3,
    workspace_id: 7,
    host_user_id: 9,
    co_hosts: [],
    host_display_name: null,
    name: "Thursday scrim",
    status: "balanced",
    settings: SETTINGS,
    created_at: null,
    lobby_count: 1,
    lobbies: [lobbyRow()],
    roster_shape: null,
    players: [],
    matches_count: 0,
    last_match_at: null,
    // Added by A8 to `CustomGame`; the fixture carries them so `bun run
    // typecheck` stays honest about the post-A shape.
    self_signup: "closed",
    self_role_edit: false,
    ...overrides,
  };
}

function match(overrides: Partial<CustomGameMatch> = {}): CustomGameMatch {
  return {
    id: 2,
    teams: [
      { slot: 1, name: "Wolves", score: 1 },
      { slot: 2, name: "Bears", score: 0 },
    ],
    winner_slot: 1,
    map_id: 5,
    map_name: "King's Row",
    map_image_path: null,
    recorded_by: 9,
    recorded_at: new Date().toISOString(),
    points_per_win_applied: null,
    lobby_index: 0,
    bans: [],
    picks: [],
    ...overrides,
  };
}

function player(overrides: Partial<CustomGamePlayer> = {}): CustomGamePlayer {
  return {
    id: 1,
    workspace_member_id: 7,
    display_name: null,
    identity: null,
    sort_order: 0,
    participation: "pool",
    role_selection_mode: "all_ranked",
    is_flex: false,
    away: false,
    roles: null,
    ranks: {},
    rank_sources: {},
    author_ranks: {},
    ...overrides,
  };
}

/** The lobby while its match is on. */
const LIVE = { state: "live", live_encounter_id: 50, live_started_at: "2026-01-01T20:00:00Z" } as const;

// The history row paints the winning team's name in the full foreground tone and the other in the dim one.
const WINNER_TONE = "text-[color:var(--aqt-fg)]";

function teamNameClass(scope: ParentNode, name: string) {
  const el = [...scope.querySelectorAll("li span")].find((s) => s.textContent === name);
  if (!el) throw new Error(`no history team named ${name}`);
  return el.className;
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

type PanelOptions = {
  canWrite?: boolean;
  activeCount?: number;
  variantIndex?: number;
  lobbyIndex?: number;
  hasMix?: boolean;
  omitSwapSeats?: boolean;
  maps?: CatalogEntityRead[];
  matches?: CustomGameMatch[];
  /** The whole mix's history, every lobby; defaults to `matches`, a one-lobby page's history. */
  mixMatches?: CustomGameMatch[];
  undoingMatchId?: number | null;
  omitUndoMatch?: boolean;
  omitPostToDiscord?: boolean;
  owner?: MixOwner;
  emptyState?: (balanceAction: ReactNode) => ReactNode;
};

function panel(current: CustomGame | undefined, props: PanelOptions) {
  const lobbyIndex = props.lobbyIndex ?? 0;
  return (
    <PickupTeamsPanel
      canWrite={props.canWrite ?? true}
      gamesLoading={false}
      gamesError={false}
      onRetryGames={vi.fn()}
      game={current}
      lobby={current?.lobbies.find((row) => row.lobby_index === lobbyIndex)}
      lobbyIndex={lobbyIndex}
      owner={props.owner ?? OW_OWNER}
      gameLoading={false}
      hasMix={props.hasMix ?? current != null}
      balancing={false}
      activeCount={props.activeCount ?? 10}
      onBalance={onBalance}
      drafting={false}
      onDraft={vi.fn()}
      roomHref={mixRoomHref(current?.id ?? 3, lobbyIndex)}
      startingMatch={false}
      onStartMatch={onStartMatch}
      cancellingMatch={false}
      onCancelMatch={onCancelMatch}
      onMakeCaptain={onMakeCaptain}
      variantIndex={props.variantIndex ?? 0}
      onVariantIndexChange={onVariantIndexChange}
      recordingOutcome={false}
      onRecordOutcome={onRecordOutcome}
      matches={props.matches ?? []}
      mixMatches={props.mixMatches ?? props.matches ?? []}
      undoingMatchId={props.undoingMatchId ?? null}
      onUndoMatch={props.omitUndoMatch ? undefined : onUndoMatch}
      maps={props.maps ?? []}
      settingNextMap={false}
      onNextMapChange={onNextMapChange}
      closingMix={false}
      onCloseMix={onCloseMix}
      onRenameTeam={onRenameTeam}
      onSwapSeats={props.omitSwapSeats ? undefined : onSwapSeats}
      onCopyHandles={onCopyHandles}
      postingToDiscord={false}
      onPostToDiscord={props.omitPostToDiscord ? undefined : onPostToDiscord}
      emptyState={props.emptyState}
    />
  );
}

async function mount(
  current: CustomGame | undefined,
  props: PanelOptions = {},
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <NextIntlClientProvider locale="en" messages={en}>
          {panel(current, props)}
        </NextIntlClientProvider>
      </QueryClientProvider>,
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

/** By accessible name: the visible label for text buttons, `aria-label` for the icon-only tools. */
function byName(scope: ParentNode, name: string) {
  return (
    [...scope.querySelectorAll("button")].find(
      (node) => node.textContent?.trim() === name || node.getAttribute("aria-label") === name,
    ) ?? null
  );
}

/** The Open room link, the accent one being the teal-tinted button. */
function roomLink(scope: ParentNode) {
  return [...scope.querySelectorAll("a")].find((node) => node.textContent?.trim() === "Open room") ?? null;
}

function inputByLabel(scope: ParentNode, label: string) {
  return scope.querySelector<HTMLInputElement>(`input[aria-label="${label}"]`);
}

// React overrides the input's own `value` setter to track changes; assigning
// through it makes React think nothing changed, so write via the prototype
// setter instead (mirrors InlineEditText.behavior.test.tsx).
const nativeValueSetter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;

async function typeInto(field: HTMLInputElement, value: string) {
  await act(async () => {
    nativeValueSetter?.call(field, value);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

function pagerLabel(scope: ParentNode) {
  return scope.querySelector('[role="status"]')?.textContent?.trim();
}

beforeEach(() => {
  document.body.innerHTML = "";
  onBalance.mockReset();
  onVariantIndexChange.mockReset();
  onRecordOutcome.mockReset();
  onNextMapChange.mockReset();
  onCloseMix.mockReset();
  onCopyHandles.mockReset();
  onRenameTeam.mockReset();
  onSwapSeats.mockReset();
  onUndoMatch.mockReset();
  onPostToDiscord.mockReset();
  onStartMatch.mockReset();
  onCancelMatch.mockReset();
  onMakeCaptain.mockReset();
  captureSpies.capture.mockReset();
  captureSpies.capturing = false;
  dndSpies.useDraggable.mockClear();
  dndSpies.useDroppable.mockClear();
});

describe("PickupTeamsPanel", () => {
  it("renders seats and ratings from the payload instead of raw JSON", async () => {
    const scope = await mount(game());

    expect(scope.textContent).toContain("karin");
    expect(scope.textContent).toContain("2900");
    expect(scope.textContent).toContain("Tolgrn");
    expect(scope.textContent).toContain("3450");
    expect(scope.textContent).not.toContain("balance_result");
    expect(scope.textContent).not.toContain('"uuid"');
  });

  it("seats every player of a League balance: five positions per team, no Overwatch role needed", async () => {
    const names = ["Zed", "Lee", "Ahri", "Jinx", "Lulu", "Kai", "Sona", "Vi", "Syn", "Ryze"];
    const positions = ["top", "jungle", "mid", "bot", "support"];
    const players = Object.fromEntries(
      names.map((name, index) => [
        String(index + 1),
        { name, ratings: { [positions[index % 5]]: 2000 + index }, role_preferences: [positions[index % 5]] },
      ]),
    );
    const rosterOf = (offset: number) =>
      Object.fromEntries(positions.map((position, index) => [position, [String(offset + index + 1)]]));
    const scope = await mount(
      game({
        lobbies: [
          lobbyRow({
            balance_result: {
              players,
              feasibility: null,
              variants: [
                {
                  teams: [
                    { id: 1, average_mmr: 2100, roster: rosterOf(0) },
                    { id: 2, average_mmr: 2200, roster: rosterOf(5) },
                  ],
                  statistics: {},
                  benched: [],
                },
              ],
            },
          }),
        ],
      }),
      { owner: LOL_OWNER },
    );

    for (const name of names) expect(scope.textContent).toContain(name);
    expect(scope.querySelectorAll("section li")).toHaveLength(10);
  });

  it("labels no seat with a role in a one-role game", async () => {
    const deadlock = {
      players: {
        "7": { name: "karin", ratings: { agent: 2900 }, role_preferences: ["agent"] },
        "8": { name: "Egor", ratings: { agent: 3100 }, role_preferences: ["agent"] },
      },
      feasibility: null,
      variants: [
        {
          teams: [
            { id: 1, average_mmr: 2900, roster: { agent: ["7"] } },
            { id: 2, average_mmr: 3100, roster: { agent: ["8"] } },
          ],
          statistics: {},
          benched: [],
        },
      ],
    };
    const scope = await mount(game({ lobbies: [lobbyRow({ balance_result: deadlock })] }), { owner: DEADLOCK_OWNER });

    expect(scope.textContent).toContain("karin");
    expect(scope.textContent).toContain("Egor");
    expect(scope.querySelector('[role="img"][aria-label="Agent"]')).toBeNull();
  });

  it("shows the option's own verdict but not who it left out -- the lineup already marks them benched", async () => {
    const scope = await mount(game());

    expect(scope.textContent).toContain("0.87");
    expect(scope.textContent).toContain("12.3");
    expect(scope.textContent).not.toContain("Egor");
  });

  it("shows the mix engine's own verdict, not just the tournament solver's", async () => {
    // What `mix_balancer` reports for a mix: its four-term total as the quality
    // score and the per-line rank gap, neither of which the tournament solver
    // produces. Off-role sits at the pool's structural floor here, so it reads
    // as unavoidable rather than as something the host should go fix.
    const scored = variant(0);
    scored.statistics = {
      mix_balancer_quality_total: 41.5,
      mix_balancer_role_fairness: 118.7,
      mmr_std_dev: 12.34,
      max_total_rating_gap: 150,
      off_role_count: 1,
      off_role_above_minimum: 0,
      sub_role_collision_count: 2,
    };
    // The floor is the pool's, so the document carries it once, not per option.
    const scope = await mount(
      game({ lobbies: [lobbyRow({ balance_result: lobby([scored], { structural_min_off_role: 1 }) })] }),
    );

    expect(scope.textContent).toContain("QUALITY 41.50");
    expect(scope.textContent).toContain("LINES 119");
    expect(scope.textContent).toContain("SPREAD 150");
    expect(scope.textContent).toContain("OFF-ROLE 1 (floor)");
    expect(scope.textContent).toContain("SUBROLE 2");
  });

  it("drops the scored pills for an option the host hand-edited", async () => {
    // `_recompute_variant_stats` nulls every solver-scored key after a seat
    // swap, because they describe the seating the solver chose. Showing the old
    // numbers next to a changed roster would be the one thing worse than
    // showing none.
    const swapped = variant(0);
    swapped.statistics = {
      composite_score: null,
      mix_balancer_quality_total: null,
      mix_balancer_role_fairness: null,
      mmr_std_dev: 12.34,
      off_role_count: 1,
    };
    const scope = await mount(game({ lobbies: [lobbyRow({ balance_result: lobby([swapped]) })] }));

    expect(scope.textContent).not.toContain("QUALITY");
    expect(scope.textContent).not.toContain("LINES");
    expect(scope.textContent).toContain("STDDEV 12.3");
    expect(scope.textContent).toContain("OFF-ROLE 1");
  });

  it("captures the verdict pills with the teams block, not the action buttons beside it", async () => {
    const scope = await mount(game());

    const captured = scope.querySelector('[data-testid="teams-capture"]');
    expect(captured).not.toBeNull();
    expect(captured?.textContent).toContain("0.87");
    expect(captured?.textContent).toContain("karin");
    expect(captured?.textContent).not.toContain("Copy image");
    expect(captured?.textContent).not.toContain("Copy handles");
    expect(captured?.textContent).not.toContain("Close mix");
  });

  it("reports a pager move to the page instead of keeping its own index", async () => {
    const scope = await mount(game());

    expect(pagerLabel(scope)).toBe("1 / 3");
    expect(byName(scope, "Previous balance option")?.hasAttribute("disabled")).toBe(true);

    await click(byName(scope, "Next balance option"));

    expect(onVariantIndexChange).toHaveBeenCalledWith(1);
    expect(onBalance).not.toHaveBeenCalled();
  });

  it("renders the option the page selected", async () => {
    const scope = await mount(game(), { variantIndex: 2 });

    expect(pagerLabel(scope)).toBe("3 / 3");
    expect(scope.textContent).toContain("3100");
  });

  it("clamps an index left pointing past a shorter result", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow({ balance_result: lobby([variant(0)]) })] }), {
      variantIndex: 7,
    });

    // One option left: the pager is gone and the first option is on screen.
    expect(pagerLabel(scope)).toBeUndefined();
    expect(scope.textContent).toContain("karin");
  });

  it("offers the empty state for a mix that has not been balanced", async () => {
    const scope = await mount(
      game({ status: "draft", lobbies: [lobbyRow({ balance_result: null, balanced_at: null })] }),
    );

    expect(scope.textContent).toContain("No teams yet");
    expect(byName(scope, "Balance teams")).not.toBeNull();
  });

  it("refuses to balance an empty lineup and says why", async () => {
    const scope = await mount(
      game({ status: "draft", lobbies: [lobbyRow({ balance_result: null, balanced_at: null })] }),
      { activeCount: 0 },
    );

    expect(byName(scope, "Balance teams")?.hasAttribute("disabled")).toBe(true);
    expect(scope.textContent).toContain("Check at least one player in the lobby");
  });

  it("balances on request when the lineup is not empty", async () => {
    const scope = await mount(
      game({ status: "draft", lobbies: [lobbyRow({ balance_result: null, balanced_at: null })] }),
    );

    await click(byName(scope, "Balance teams"));

    expect(onBalance).toHaveBeenCalledTimes(1);
  });

  it("hands Balance to the host's checklist instead of repeating it in the footer", async () => {
    const scope = await mount(
      game({ status: "draft", lobbies: [lobbyRow({ balance_result: null, balanced_at: null })] }),
      { emptyState: (balanceAction) => <section aria-label="checklist">{balanceAction}</section> },
    );

    expect(scope.textContent).not.toContain("No teams yet");
    const balances = [...scope.querySelectorAll("button")].filter((node) => node.textContent?.trim() === "Balance teams");
    expect(balances).toHaveLength(1);
    expect(balances[0]?.closest('[aria-label="checklist"]')).not.toBeNull();

    await click(balances[0]);
    expect(onBalance).toHaveBeenCalledTimes(1);
  });

  it("records a live match's result only on a deliberate click, without closing the mix", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow(LIVE)] }));

    expect(onRecordOutcome).not.toHaveBeenCalled();

    await click(byName(scope, "Draw"));
    expect(onRecordOutcome).toHaveBeenCalledWith({ outcome: { winner: null }, lobbyIndex: 0 });

    await click(byName(scope, "Team 2 win"));
    expect(onRecordOutcome).toHaveBeenLastCalledWith({ outcome: { winner: 2 }, lobbyIndex: 0 });
  });

  it("shows the mix's next map, with its mode, inside the captured block", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow({ next_map_id: 5 })] }), { maps: CATALOGUE });

    const captured = scope.querySelector('[data-testid="teams-capture"]');
    expect(captured?.textContent).toContain("King's Row");
    expect(captured?.textContent).toContain("Hybrid");
    expect(captured?.textContent).not.toContain("Not rolled yet");
  });

  it("rolls inside the chosen mode and hands the verdict to the page", async () => {
    const scope = await mount(game(), { maps: CATALOGUE });

    expect(scope.textContent).toContain("Not rolled yet");
    expect(byName(scope, "Hybrid")?.getAttribute("aria-pressed")).toBe("false");

    await click(byName(scope, "Hybrid"));
    expect(byName(scope, "Hybrid")?.getAttribute("aria-pressed")).toBe("true");

    await click(byName(scope, "Roll"));
    // Hybrid has exactly one competitive map, so the roll is deterministic.
    expect(onNextMapChange).toHaveBeenCalledWith(5);
  });

  it("rolls past a map another lobby played while the mode still has an unplayed one", async () => {
    // Always the first map of the pool: without the other lobby's history that is Ilios.
    const random = vi.spyOn(Math, "random").mockReturnValue(0);
    const twoLobbies = game({ lobby_count: 2, lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })] });
    // Lobby A played Ilios; lobby B's room lists none of A's matches, but its roll still skips Ilios.
    const scope = await mount(twoLobbies, {
      lobbyIndex: 1,
      maps: CATALOGUE,
      matches: [],
      mixMatches: [match({ id: 12, lobby_index: 0, map_id: 6, map_name: "Ilios" })],
    });

    await click(byName(scope, "Control"));
    await click(byName(scope, "Roll"));
    random.mockRestore();

    expect(onNextMapChange).toHaveBeenCalledWith(7);
  });

  it("hides the roll controls from a read-only viewer, and the whole strip until something is rolled", async () => {
    const nothingRolled = await mount(game(), { maps: CATALOGUE, canWrite: false });
    expect(nothingRolled.textContent).not.toContain("Next map");

    document.body.innerHTML = "";
    const rolled = await mount(game({ lobbies: [lobbyRow({ next_map_id: 6 })] }), {
      maps: CATALOGUE,
      canWrite: false,
    });
    expect(rolled.textContent).toContain("Ilios");
    expect(byName(rolled, "Roll")).toBeNull();
    expect(byName(rolled, "Hybrid")).toBeNull();
  });

  it("offers no next map at all in a game with a single competitive map", async () => {
    const singleMap = [CATALOGUE[0], catalogMap(6, CONTROL, { name: "Ilios", attrs: { in_competitive: false } })];
    const scope = await mount(game({ lobbies: [lobbyRow({ next_map_id: 5 })] }), { maps: singleMap });

    expect(scope.textContent).not.toContain("Next map");
    expect(scope.textContent).not.toContain("King's Row");
    expect(byName(scope, "Roll")).toBeNull();
  });

  it("lets the host pick the next map by hand through the combobox", async () => {
    const scope = await mount(game(), { maps: CATALOGUE });

    // The trigger reads "No map" until a map is set.
    await click(byName(scope, "No map"));
    const option = [...document.body.querySelectorAll<HTMLElement>("[cmdk-item]")].find(
      (node) => node.textContent?.trim() === "Ilios",
    );
    await click(option);

    expect(onNextMapChange).toHaveBeenCalledWith(6);
  });

  it("lets the host close the mix independently of recording a result, after confirming", async () => {
    const scope = await mount(game());

    await click(byName(scope, "Close mix"));
    expect(onCloseMix).not.toHaveBeenCalled();

    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "Close this mix?",
    );

    await click(byName(document, "Yes, close mix"));
    expect(onCloseMix).toHaveBeenCalledTimes(1);
  });

  it("offers no result controls to a viewer or on a closed mix -- the history is the record", async () => {
    const scope = await mount(game({ status: "completed" }), { canWrite: false });

    expect(byName(scope, "Team 1 win")).toBeNull();
    expect(byName(scope, "Draw")).toBeNull();
    expect(byName(scope, "Close mix")).toBeNull();
  });

  it("shows the configured points-per-win on the win buttons, never on Draw", async () => {
    const scope = await mount(game({ settings: { ...SETTINGS, points_per_win: 25 }, lobbies: [lobbyRow(LIVE)] }));

    expect(byName(scope, "Team 1 win +25")).not.toBeNull();
    expect(byName(scope, "Team 2 win +25")).not.toBeNull();
    expect(byName(scope, "Draw")).not.toBeNull();
  });

  it("omits the points hint once no rank-adjustment is configured", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow(LIVE)] }));

    expect(byName(scope, "Team 1 win")).not.toBeNull();
  });

  it("renders the recorded match history the page hands it", async () => {
    const scope = await mount(game(), { matches: [match()] });

    expect(scope.textContent).toContain("Match history");
    expect(scope.textContent).toContain("Wolves");
    expect(scope.textContent).toContain("Bears");
    expect(scope.textContent).toContain("King's Row");
  });

  it("marks only the winning team of a recorded round as ahead", async () => {
    const scope = await mount(game(), { matches: [match()] });

    expect(scope.textContent).toContain("1 : 0");
    expect(teamNameClass(scope, "Wolves")).toContain(WINNER_TONE);
    expect(teamNameClass(scope, "Bears")).not.toContain(WINNER_TONE);
  });

  it("shows a drawn round as nil-nil with neither team ahead", async () => {
    const scope = await mount(game(), {
      matches: [
        match({
          teams: [
            { slot: 1, name: "Wolves", score: 0 },
            { slot: 2, name: "Bears", score: 0 },
          ],
          winner_slot: null,
        }),
      ],
    });

    expect(scope.textContent).toContain("0 : 0");
    expect(scope.textContent).toContain("Wolves");
    expect(scope.textContent).toContain("Bears");
    expect(teamNameClass(scope, "Wolves")).not.toContain(WINNER_TONE);
    expect(teamNameClass(scope, "Bears")).not.toContain(WINNER_TONE);
  });

  it("offers the undo only on the newest recorded match", async () => {
    const scope = await mount(game(), {
      matches: [match({ id: 9 }), match({ id: 8 })],
    });

    expect(scope.querySelectorAll('button[aria-label="Undo this match"]')).toHaveLength(1);
  });

  it("withholds the undo from a read-only viewer and from a page offering no handler", async () => {
    const readOnly = await mount(game(), { matches: [match()], canWrite: false });
    expect(readOnly.querySelector('button[aria-label="Undo this match"]')).toBeNull();

    const noHandler = await mount(game(), { matches: [match()], omitUndoMatch: true });
    expect(noHandler.querySelector('button[aria-label="Undo this match"]')).toBeNull();
  });

  it("names the rank points it will give back, and only undoes after confirming", async () => {
    const scope = await mount(game(), {
      matches: [match({ id: 9, points_per_win_applied: 25 })],
    });

    await click(scope.querySelector('button[aria-label="Undo this match"]'));
    expect(onUndoMatch).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "moves every player's rank back by 25 points",
    );

    await click(byName(document, "Undo match"));
    expect(onUndoMatch).toHaveBeenCalledWith(9);
  });

  it("says so plainly when the match moved no rank points", async () => {
    const scope = await mount(game(), { matches: [match()] });

    await click(scope.querySelector('button[aria-label="Undo this match"]'));

    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "No rank points were applied.",
    );
  });

  it("hides the match history section until something has been recorded", async () => {
    const scope = await mount(game());

    expect(scope.textContent).not.toContain("Match history");
  });

  it("hands the handle copy to the page", async () => {
    const scope = await mount(game());

    await click(byName(scope, "Copy handles"));
    expect(onCopyHandles).toHaveBeenCalledTimes(1);
  });

  it("gives a read-only viewer the teams but no controls -- not even the pager", async () => {
    // The option on screen is the host's to choose (the mix's own
    // `selected_variant_index`): a viewer paging their own copy would be
    // reading out a matchup nobody is playing.
    const scope = await mount(game(), { canWrite: false, variantIndex: 1 });

    expect(byName(scope, "Balance teams")).toBeNull();
    expect(scope.textContent).toContain("karin");
    expect(byName(scope, "Next balance option")).toBeNull();
    expect(byName(scope, "Previous balance option")).toBeNull();
    expect(pagerLabel(scope)).toBeUndefined();
  });

  it("separates no mix at all from a mix with no teams", async () => {
    const scope = await mount(undefined, { hasMix: false });

    expect(scope.textContent).toContain("No mixes yet");
    expect(scope.textContent).not.toContain("No teams yet");
  });

  it("lets the host rename a team through the pencil affordance", async () => {
    const scope = await mount(game());

    const pencils = [...scope.querySelectorAll('button[aria-label="Edit team name"]')];
    expect(pencils).toHaveLength(2);

    await click(pencils[0]);
    const field = inputByLabel(scope, "team name");
    expect(field?.value).toBe("Team 1");
    await typeInto(field as HTMLInputElement, "Wolves");
    await click(scope.querySelector('button[aria-label="Save team name"]'));

    expect(onRenameTeam).toHaveBeenCalledWith(0, "Wolves");
  });

  it("hides the rename pencil for a read-only viewer", async () => {
    const scope = await mount(game(), { canWrite: false });

    expect(scope.querySelectorAll('button[aria-label="Edit team name"]')).toHaveLength(0);
  });

  it("withholds the rename pencils while the card is being captured", async () => {
    captureSpies.capturing = true;
    const scope = await mount(game());

    expect(scope.querySelectorAll('button[aria-label="Edit team name"]')).toHaveLength(0);
    // The names themselves stay in the picture.
    expect(scope.querySelector('[data-testid="teams-capture"]')?.textContent).toContain("Team 1");
  });

  it("shows a host's saved team name instead of the computed default", async () => {
    const scope = await mount(
      game({ settings: { ...SETTINGS, team_names: { "0": "Wolves" } }, lobbies: [lobbyRow(LIVE)] }),
    );

    expect(scope.textContent).toContain("Wolves");
    // The second team keeps its computed default; the win buttons pick up
    // the same override so the scoreline reads the same name as the column.
    expect(byName(scope, "Wolves win")).not.toBeNull();
    expect(byName(scope, "Team 2 win")).not.toBeNull();
  });

  it("wires every seat as a drag source and drop target for a host who can rebalance manually", async () => {
    await mount(game());

    // Every seat across both teams (3 in the fixture) is both draggable and
    // droppable, and none of them are disabled for a host with a swap handler.
    expect(dndSpies.useDraggable).toHaveBeenCalledTimes(3);
    expect(dndSpies.useDroppable).toHaveBeenCalledTimes(3);
    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: false });
    }
    for (const call of dndSpies.useDroppable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: false });
    }
  });

  it("disables seat dragging for a read-only viewer", async () => {
    await mount(game(), { canWrite: false });

    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: true });
    }
  });

  it("disables seat dragging when the page offers no swap handler", async () => {
    await mount(game(), { omitSwapSeats: true });

    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: true });
    }
  });

  it("offers no Post to Discord until a channel is configured", async () => {
    const scope = await mount(game());

    expect(byName(scope, "Post to Discord")).toBeNull();
  });

  it("posts the option on screen to the workspace channel", async () => {
    // The workspace's channel is the only target a mix has: nothing about the
    // mix names one, so the button follows the workspace alone.
    const withChannel = game({ settings: { ...SETTINGS, workspace_discord_channel_id: "123" } });
    const scope = await mount(withChannel);

    await click(byName(scope, "Post to Discord"));
    expect(onPostToDiscord).toHaveBeenCalledWith(0);

    // The pager's option is what a lobby is reading, so that is what goes out.
    document.body.innerHTML = "";
    const second = await mount(withChannel, { variantIndex: 1 });
    await click(byName(second, "Post to Discord"));
    expect(onPostToDiscord).toHaveBeenLastCalledWith(1);
  });

  it("hides Post to Discord from a read-only viewer", async () => {
    const scope = await mount(game({ settings: { ...SETTINGS, workspace_discord_channel_id: "123" } }), {
      canWrite: false,
    });

    expect(byName(scope, "Post to Discord")).toBeNull();
  });

  it("reads the matchup from the mix's first lobby, not from the mix itself", async () => {
    // The four columns moved to `custom_game_lobby`; a mix whose lobby row
    // carries the document must render exactly what the flat shape rendered.
    const scope = await mount(game({ lobbies: [lobbyRow({ next_map_id: 6 })] }), {
      maps: CATALOGUE,
      variantIndex: 2,
    });

    expect(scope.textContent).toContain("karin");
    expect(scope.textContent).toContain("3100");
    expect(pagerLabel(scope)).toBe("3 / 3");
    expect(scope.querySelector('[data-testid="teams-capture"]')?.textContent).toContain("Ilios");
  });

  it("records a result for the lobby it is showing, not always the first", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1, ...LIVE })],
    });
    const scope = await mount(twoLobbies, { lobbyIndex: 1, variantIndex: 1 });

    await click(byName(scope, "Team 1 win"));

    expect(onRecordOutcome).toHaveBeenCalledWith({ outcome: { winner: 1 }, lobbyIndex: 1 });
  });

  it("renames lobby B's teams at their global indices, not at 0 and 1", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
    });
    const scope = await mount(twoLobbies, { lobbyIndex: 1 });

    const pencils = [...scope.querySelectorAll('button[aria-label="Edit team name"]')];
    await click(pencils[0]);
    const field = inputByLabel(scope, "team name");
    await typeInto(field as HTMLInputElement, "Ravens");
    await click(scope.querySelector('button[aria-label="Save team name"]'));

    // A: 0-1, B: 2-3 -- the same `CustomGameTeamName.team_index` the host's
    // override for lobby A already uses.
    expect(onRenameTeam).toHaveBeenCalledWith(2, "Ravens");
  });

  it("shows lobby B its own stored name override", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
      settings: { ...SETTINGS, team_names: { "0": "Wolves", "2": "Ravens" } },
    });
    const scope = await mount(twoLobbies, { lobbyIndex: 1 });

    expect(scope.textContent).toContain("Ravens");
    expect(scope.textContent).not.toContain("Wolves");
  });

  it("asks before rebalancing a lobby whose lineup is still unrecorded", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow({ lineup_recorded: false })] }));

    await click(byName(scope, "Balance teams"));
    expect(onBalance).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "has not been recorded",
    );

    await click(byName(document, "Balance anyway"));
    expect(onBalance).toHaveBeenCalledTimes(1);
  });

  it("balances straight away once this lobby's last lineup has been recorded", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow({ lineup_recorded: true })] }));

    await click(byName(scope, "Balance teams"));

    expect(onBalance).toHaveBeenCalledTimes(1);
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
  });

  it("offers an undo on the newest match of each lobby, not only on the newest of the mix", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
    });
    const scope = await mount(twoLobbies, {
      matches: [
        match({ id: 12, lobby_index: 0 }),
        match({ id: 11, lobby_index: 1 }),
        match({ id: 10, lobby_index: 0 }),
      ],
    });

    // 12 is A's newest, 11 is B's newest; 10 sits under 12 in the same lobby.
    expect(scope.querySelectorAll('button[aria-label="Undo this match"]')).toHaveLength(2);
  });

  it("marks which lobby each recorded match belongs to once the mix runs two", async () => {
    const twoLobbies = game({
      lobby_count: 2,
      lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1 })],
    });
    const scope = await mount(twoLobbies, {
      matches: [match({ id: 12, lobby_index: 0 }), match({ id: 11, lobby_index: 1 })],
    });

    const chips = [...scope.querySelectorAll('[data-testid="match-lobby"]')].map((node) =>
      node.textContent?.trim(),
    );
    expect(chips).toEqual(["A", "B"]);
  });

  it("leaves the history unchipped while the mix has run one lobby all along", async () => {
    const scope = await mount(game(), { matches: [match({ id: 12 })] });

    expect(scope.querySelector('[data-testid="match-lobby"]')).toBeNull();
  });

  it("shows a round's hero bans in the order they were made", async () => {
    const scope = await mount(game({ discipline: "overwatch" }), {
      matches: [match({ id: 12, bans: [{ slot: 2, item_id: 102 }, { slot: 1, item_id: 101 }, { slot: 2, item_id: 999 }] })],
    });
    await act(async () => {
      await tick();
    });

    const strip = scope.querySelector('[aria-label="Bans"]');
    // A hero the catalog no longer has still shows, by its id.
    expect([...(strip?.querySelectorAll("[title]") ?? [])].map((node) => node.getAttribute("title"))).toEqual([
      "Genji",
      "Ana",
      "#999",
    ]);
  });

  it("leaves a round without bans with no ban strip", async () => {
    const scope = await mount(game({ discipline: "overwatch" }), { matches: [match({ id: 12 })] });

    expect(scope.querySelector('[aria-label="Bans"]')).toBeNull();
  });

  it("shows whose hero each pick of a round was", async () => {
    const scope = await mount(game({ discipline: "overwatch" }), {
      matches: [match({ id: 12, picks: [{ slot: 1, member_id: 7, name: "Kiri main", item_id: 101 }] })],
    });
    await act(async () => {
      await tick();
    });

    const list = scope.querySelector('[aria-label="Picks"]');
    expect(list?.textContent).toContain("Kiri main");
    expect([...(list?.querySelectorAll("[title]") ?? [])].map((node) => node.getAttribute("title"))).toEqual(["Ana"]);
  });

  it("starts the match from a Ready lobby, which offers no result yet", async () => {
    const scope = await mount(game());

    expect(byName(scope, "Draw")).toBeNull();
    expect(roomLink(scope)).toBeNull();
    await click(byName(scope, "Start match"));

    expect(onStartMatch).toHaveBeenCalledWith(false);
  });

  it("warns before starting with an away player seated, and starts once confirmed", async () => {
    const scope = await mount(game({ players: [player({ workspace_member_id: 8, away: true })] }));

    await click(byName(scope, "Start match"));
    expect(onStartMatch).not.toHaveBeenCalled();
    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain("Start with away players?");

    await click(byName(document, "Start anyway"));
    expect(onStartMatch).toHaveBeenCalledWith(false);
  });

  it("freezes a live lineup: results and Cancel match, but no balance, pager, swap or captaincy", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow(LIVE)] }));

    expect(scope.textContent).toContain("Lineup frozen while the match is live");
    expect(byName(scope, "Balance teams")).toBeNull();
    expect(byName(scope, "Next balance option")).toBeNull();
    expect(byName(scope, "Start match")).toBeNull();
    // The match plays out in the room; the desk links there quietly.
    expect(roomLink(scope)?.getAttribute("href")).toBe("/balancer/mix/3/lobby/A");
    expect(roomLink(scope)?.className).not.toContain("--aqt-teal");
    expect(scope.querySelectorAll('button[aria-label="Make captain"]')).toHaveLength(0);
    // The three seats still render; none of them can be dragged.
    expect(scope.querySelectorAll("section li")).toHaveLength(3);
    for (const name of ["karin", "DemonDimon", "Tolgrn"]) expect(scope.textContent).toContain(name);
    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: true });
    }

    await click(byName(scope, "Cancel match"));
    expect(onCancelMatch).not.toHaveBeenCalled();
    await click(byName(document, "Yes, cancel the match"));
    expect(onCancelMatch).toHaveBeenCalledTimes(1);
  });

  it("sends Pre-game to the room: the frozen lineup, a loud Open room and Cancel match, no ban board", async () => {
    const pregame = lobbyRow({ state: "pregame", live_encounter_id: 50, live_started_at: "2026-01-01T20:00:00Z" });
    const scope = await mount(game({ hero_ban_preset: "hero_bo1_simple", lobbies: [pregame] }));

    expect(scope.textContent).toContain("Lineup frozen while the match is live");
    expect(scope.textContent).toContain("Hero bans and picks are on in the room");
    expect(roomLink(scope)?.getAttribute("href")).toBe("/balancer/mix/3/lobby/A");
    expect(roomLink(scope)?.className).toContain("--aqt-teal");
    expect(scope.querySelectorAll("section li")).toHaveLength(3);
    expect(byName(scope, "Draw")).toBeNull();
    expect(byName(scope, "Balance teams")).toBeNull();
    expect(byName(scope, "Start match")).toBeNull();

    await click(byName(scope, "Cancel match"));
    await click(byName(document, "Yes, cancel the match"));
    expect(onCancelMatch).toHaveBeenCalledTimes(1);
  });

  it("points a drafting lobby at its room instead of a board or its teams", async () => {
    for (const state of ["draft_setup", "draft_live"] as const) {
      const twoLobbies = game({
        lobby_count: 2,
        lobbies: [lobbyRow(), lobbyRow({ lobby_index: 1, state, draft_session_id: 77 })],
      });
      const scope = await mount(twoLobbies, { lobbyIndex: 1, canWrite: false });

      expect(scope.textContent).toContain("Captains are drafting in the room");
      expect(scope.textContent).toContain("The teams show up here once the draft ends.");
      expect(roomLink(scope)?.getAttribute("href")).toBe("/balancer/mix/3/lobby/B");
      expect(roomLink(scope)?.className).toContain("--aqt-teal");
      expect(scope.textContent).not.toContain("karin");
      expect(byName(scope, "Balance teams")).toBeNull();
    }
  });

  it("tells a viewer a live lineup is frozen, without handing them the result or Cancel match", async () => {
    const scope = await mount(game({ lobbies: [lobbyRow(LIVE)] }), { canWrite: false });

    expect(scope.textContent).toContain("Lineup frozen while the match is live");
    expect(byName(scope, "Team 1 win")).toBeNull();
    expect(byName(scope, "Draw")).toBeNull();
    expect(byName(scope, "Cancel match")).toBeNull();
  });

  it("crowns each team's captain and lets the host hand the crown to another seat", async () => {
    const captained = lobby([
      {
        ...variant(0),
        teams: variant(0).teams.map((team, index) => ({ ...team, captain_member_id: index === 0 ? 8 : 9 })),
      },
    ]);
    const scope = await mount(game({ lobbies: [lobbyRow({ balance_result: captained })] }));

    // DemonDimon (8) and Tolgrn (9) wear the crown, so only karin (7) can be made captain.
    const makers = [...scope.querySelectorAll('button[aria-label="Make captain"]')];
    expect(makers).toHaveLength(1);
    await click(makers[0]);

    expect(onMakeCaptain).toHaveBeenCalledWith(7);
  });
});
