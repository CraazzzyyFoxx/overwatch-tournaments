// @vitest-environment happy-dom
//
// The mix sheet stages every edit — bench, role priority, roles on/off, ranks —
// and writes none of it until Save, which makes four things load-bearing:
//
//  1. nothing reaches the mutation layer before Save, however many keystrokes,
//     toggles or clears happen first;
//  2. one Save is one write per concern: a combined patch for bench/roles, and
//     at most one rank-book write, however many fields changed;
//  3. the rank field shows the *effective* rank and the layer it came from, and
//     typing stores the correction in this host's own book — a host who sees
//     2700 and types 3000 must not be silently editing a different number;
//  4. role order is the host's stored order, never re-derived from a rank —
//     turning a role on appends it, it does not jump to a rank-sorted slot.
//
// There is no fourth rank field: the per-mix rank pin is gone, so every rank
// the sheet writes goes to the author's book and nowhere else.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { CustomGamePlayer, MixMemberStats } from "@/services/custom-game.service";

import { PickupPlayerSheet } from "./PickupPlayerSheet";
import { DEADLOCK_OWNER, OW_OWNER } from "./mix-owner.fixture";
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

vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/RankHistory", () => ({ default: () => null }));
// Drag itself is not what this pins, and dnd-kit resolves its own React copy
// under pnpm, so the sortable wrapper and its hook render inertly here.
vi.mock("@/components/kit/SortableRows", () => ({
  SortableRows: ({
    items,
    children,
  }: {
    items: readonly unknown[];
    children: (item: unknown, index: number) => unknown;
  }) => <div>{items.map((item, index) => children(item, index))}</div>,
  useSortableRow: () => ({ ref: () => {}, style: {}, handleProps: {}, isDragging: false }),
  SortableGrip: () => null,
}));
// The mix owner with a three-tier grid: the rank fields label and slide against `owner.grid`.
const OWNER: MixOwner = {
  ...OW_OWNER,
  grid: {
    tiers: [
      { number: 1, name: "Bronze", rank_min: 1000, rank_max: 1999, icon_url: "" },
      { number: 2, name: "Silver", rank_min: 2000, rank_max: 2999, icon_url: "" },
      { number: 3, name: "Gold", rank_min: 3000, rank_max: 3999, icon_url: "" },
    ],
  } as MixOwner["grid"],
};

const onSave = vi.fn();
const onOpenChange = vi.fn();
const onRemove = vi.fn();

function row(overrides: Partial<CustomGamePlayer> = {}): CustomGamePlayer {
  return {
    id: 1,
    workspace_member_id: 7,
    display_name: null,
    display: { name: "Aria#1111", tag: null, canonical: "Aria#1111", snapshot: null },
    identity: { provider: "battlenet", handle: "Aria#1111" },
    sort_order: 0,
    participation: "pool",
    roles: ["tank", "damage"].map((role) => ({ dimension: "player_role", role })),
    ranks: { tank: 3300, damage: 2700, support: 2900 },
    rank_sources: { tank: "author", damage: "workspace", support: "native" },
    author_ranks: { tank: 3300 },
    away: false,
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(
  value: CustomGamePlayer | null = row(),
  mixStats: MixMemberStats | null = null,
  lobbyCount = 1,
  owner: MixOwner = OWNER,
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    // The rank crests also ask for the current workspace's own grid, through the query cache.
    createRoot(container).render(
      <QueryClientProvider client={new QueryClient()}>
        <NextIntlClientProvider locale="en" messages={en}>
          <PickupPlayerSheet
            discipline="overwatch"
            owner={owner}
            row={value}
            mixStats={mixStats}
            lobbyCount={lobbyCount}
            canEdit
            saving={false}
            onOpenChange={onOpenChange}
            onSave={onSave}
            onRemove={onRemove}
          />
        </NextIntlClientProvider>
      </QueryClientProvider>,
    );
  });
  await act(async () => {
    await tick();
  });
  // Radix portals the sheet, so the content is a sibling of the mount point.
  return document.body;
}

/** Every rank field, in render order. */
function rankFields(scope: ParentNode) {
  return [...scope.querySelectorAll<HTMLInputElement>('input[inputmode="numeric"]')];
}

/** React tracks the DOM value itself, so a plain assignment is ignored. */
function type(node: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(node, value);
    node.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
  });
}

function clearButtons(scope: ParentNode) {
  return [...scope.querySelectorAll("button")].filter(
    (node) => node.textContent?.trim() === "Clear",
  );
}

function findButton(scope: ParentNode, text: string) {
  const button = [...scope.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === text,
  );
  if (!button) throw new Error(`No button with text "${text}"`);
  return button;
}

function click(node: Element) {
  return act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  onSave.mockReset();
  onOpenChange.mockReset();
  onRemove.mockReset();
});

describe("PickupPlayerSheet ranks", () => {
  it("shows every role's effective rank and names the layer it came from", async () => {
    const scope = await mount();

    expect(rankFields(scope).map((node) => node.value)).toEqual(["3300", "2700", "2900"]);
    expect(scope.textContent).toContain("Mine");
    expect(scope.textContent).toContain("Workspace");
    expect(scope.textContent).toContain("Overwatch");
  });

  it("stages a typed rank locally and writes it only once Save is pressed", async () => {
    const scope = await mount();

    await type(rankFields(scope)[1], "3");
    await type(rankFields(scope)[1], "30");
    await type(rankFields(scope)[1], "3000");
    expect(onSave).not.toHaveBeenCalled();

    await click(findButton(scope, "Save"));

    expect(onSave).toHaveBeenCalledTimes(1);
    const [patch, rankChange] = onSave.mock.calls[0];
    expect(patch).toEqual({
      participation: "pool",
      roles: ["tank", "damage"].map((role) => ({ dimension: "player_role", role })),
      is_flex: false,
      away: false,
    });
    expect(rankChange).toEqual({ ranks: { damage: 3000 }, clear: [] });
  });

  it("offers Clear only where the host has an entry of their own, and stages it for Save", async () => {
    const scope = await mount();

    // Tank alone comes from the author's own book; damage/support are inherited, so
    // a Clear on either would drop nothing.
    const buttons = clearButtons(scope);
    expect(buttons).toHaveLength(1);

    await click(buttons[0]);
    expect(onSave).not.toHaveBeenCalled();

    await click(findButton(scope, "Save"));

    const [, rankChange] = onSave.mock.calls[0];
    expect(rankChange).toEqual({ ranks: {}, clear: ["tank"] });
  });

  it("sends no rank-book write at all when no rank field was touched", async () => {
    const scope = await mount();

    await click(findButton(scope, "Save"));

    const [, rankChange] = onSave.mock.calls[0];
    expect(rankChange).toBeNull();
  });

  it("has no per-mix rank pin left to edit", async () => {
    const scope = await mount();

    // Three role fields and nothing else: the mix-only override is gone, so a
    // rank typed here can only ever land in the author's own book.
    expect(rankFields(scope)).toHaveLength(3);
    expect(scope.textContent).not.toContain("Rank for this mix");
  });

  // The sheet labels ranks on `owner.grid` (the owner game's ladder, see `buildMixOwner`) -- never another game's tiers.
  it("labels ranks with the mix owner's grid", async () => {
    const scope = await mount();

    // 3300 is "Gold" on the owner's three-tier grid, 2700 and 2900 are "Silver".
    expect(scope.textContent).toContain("Gold");
    expect(scope.textContent).toContain("Silver");
    expect(scope.textContent).not.toContain("Diamond 2");
  });

  it("has no labels at all while the owner's grid is missing, instead of another game's", async () => {
    const scope = await mount(row(), null, 1, { ...OWNER, grid: { tiers: [] } });

    expect(scope.textContent).not.toContain("Gold");
    expect(scope.textContent).not.toContain("Silver");
    expect(scope.textContent).toContain("No rank yet");
  });

  it("edits a one-role game's rank alone and never sends Full flex", async () => {
    const scope = await mount(
      row({
        identity: { provider: "steam", handle: "206464648" },
        roles: null,
        ranks: { agent: 2900 },
        rank_sources: { agent: "native" },
        author_ranks: {},
        is_flex: true,
      }),
      null,
      1,
      { ...DEADLOCK_OWNER, grid: OWNER.grid },
    );

    // No role or Full flex control: the one switch left is Away, which every game has.
    expect(
      [...scope.querySelectorAll('[role="switch"]')].map((node) => node.getAttribute("aria-label")),
    ).toEqual(["Away"]);
    expect(scope.textContent).not.toContain("Roles and ranks");
    // The heading names the rank alone.
    expect([...scope.querySelectorAll("h3")].map((node) => node.textContent)).toContain("Rank");
    await type(rankFields(scope)[0], "3100");
    await click(findButton(scope, "Save"));

    const [patch, rankChange] = onSave.mock.calls[0];
    // A one-role game has no order to write: `null` is "every ranked role".
    expect(patch).toEqual({ participation: "pool", roles: null, is_flex: false, away: false });
    expect(rankChange).toEqual({ ranks: { agent: 3100 }, clear: [] });
  });

  // A stored `[]` (or a `null` with no rank yet) seats nobody once the first rank lands unless Save writes `null`:
  // the balance would refuse the player with `missing_ranked_role`.
  it.each<[string, CustomGamePlayer["roles"]]>([
    ["no role order yet", null],
    ["an empty role order", []],
  ])("saves a one-role player's first rank with every role on, from %s", async (_case, roles) => {
    const scope = await mount(
      row({
        identity: { provider: "steam", handle: "206464648" },
        roles,
        ranks: {},
        rank_sources: {},
        author_ranks: {},
      }),
      null,
      1,
      { ...DEADLOCK_OWNER, grid: OWNER.grid },
    );

    await type(rankFields(scope)[0], "2900");
    expect(scope.textContent).not.toContain("balance will reject this mix");
    await click(findButton(scope, "Save"));

    const [patch, rankChange] = onSave.mock.calls[0];
    expect(patch).toEqual({ participation: "pool", roles: null, is_flex: false, away: false });
    expect(rankChange).toEqual({ ranks: { agent: 2900 }, clear: [] });
  });
});

describe("PickupPlayerSheet priority", () => {
  it("keeps the host's stored role order instead of re-sorting by rank", async () => {
    // Stored order says damage-then-tank; the ranks say the opposite (tank
    // outranks damage). The order shown, and the order Save writes, must stay
    // exactly what the host stored.
    const scope = await mount(
      row({ roles: ["damage", "tank"].map((role) => ({ dimension: "player_role", role })), ranks: { tank: 3300, damage: 2700, support: 2900 } }),
    );

    expect(rankFields(scope).map((node) => node.value)).toEqual(["2700", "3300", "2900"]);

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch.roles).toEqual(["damage", "tank"].map((role) => ({ dimension: "player_role", role })));
  });

  it("appends a role turned on to the end of the order, not a rank-sorted slot", async () => {
    // Support outranks both selected roles, but switching it on must not jump
    // it to the front.
    const scope = await mount(
      row({ roles: ["tank", "damage"].map((role) => ({ dimension: "player_role", role })), ranks: { tank: 2000, damage: 2700, support: 4000 } }),
    );

    const supportSwitch = scope.querySelector<HTMLElement>('[aria-label="Support for Aria#1111"]');
    if (!supportSwitch) throw new Error("Support switch not found");
    await click(supportSwitch);

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch.roles).toEqual(["tank", "damage", "support"].map((role) => ({ dimension: "player_role", role })));
  });

  it("drops a role turned off from the order without touching the rest", async () => {
    const scope = await mount(row({ roles: ["tank", "damage"].map((role) => ({ dimension: "player_role", role })) }));

    const tankSwitch = scope.querySelector<HTMLElement>('[aria-label="Tank for Aria#1111"]');
    if (!tankSwitch) throw new Error("Tank switch not found");
    await click(tankSwitch);

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch.roles).toEqual([{ dimension: "player_role", role: "damage" }]);
  });
});

describe("PickupPlayerSheet bench", () => {
  it("stages a status change and writes both fields with the same Save as everything else", async () => {
    const scope = await mount();

    const benchedOption = scope.querySelector<HTMLElement>('[aria-label="Benched for Aria#1111"]');
    if (!benchedOption) throw new Error("Benched option not found");
    await click(benchedOption);
    expect(onSave).not.toHaveBeenCalled();

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch).toMatchObject({ participation: "benched" });
  });

  it("guarantees a seat when Must play is picked", async () => {
    const scope = await mount();

    const mustPlayOption = scope.querySelector<HTMLElement>('[aria-label="Must play for Aria#1111"]');
    if (!mustPlayOption) throw new Error("Must play option not found");
    await click(mustPlayOption);

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch).toMatchObject({ participation: "must_play" });
  });

  it("starts on the player's current status", async () => {
    const scope = await mount(row({ participation: "benched" }));

    expect(
      scope.querySelector('[aria-label="Benched for Aria#1111"]')?.getAttribute("aria-checked"),
    ).toBe("true");
  });
});

describe("PickupPlayerSheet Cancel", () => {
  it("discards every staged edit and never calls onSave", async () => {
    const scope = await mount();

    await type(rankFields(scope)[1], "3000");
    await click(findButton(scope, "Cancel"));

    expect(onSave).not.toHaveBeenCalled();
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });
});

describe("PickupPlayerSheet remove", () => {
  it("removes the player immediately, outside of Save", async () => {
    const scope = await mount();

    await click(findButton(scope, "Remove Aria#1111 from this mix"));

    expect(onRemove).toHaveBeenCalledTimes(1);
    expect(onSave).not.toHaveBeenCalled();
  });
});

describe("PickupPlayerSheet mix record", () => {
  function stats(overrides: Partial<MixMemberStats> = {}): MixMemberStats {
    return {
      workspace_member_id: 7,
      display_name: null,
      display: { name: "Aria#1111", tag: null, canonical: "Aria#1111", snapshot: null },
      identity: { provider: "battlenet", handle: "Aria#1111" },
      games: 20,
      wins: 12,
      losses: 8,
      draws: 0,
      win_rate: 0.6,
      streak: 3,
      last_played_at: "2026-01-05T20:00:00Z",
      by_role: { tank: { games: 20, wins: 12, losses: 8, draws: 0 } },
      ...overrides,
    };
  }

  it("captions the header with the player's record across every mix", async () => {
    const scope = await mount(row(), stats());

    expect(scope.textContent).toContain("Mixes: 12–8 · 60% · W3");
  });

  it("drops the streak from the caption once the run is broken", async () => {
    const scope = await mount(row(), stats({ streak: 0 }));

    expect(scope.textContent).toContain("Mixes: 12–8 · 60%");
    expect(scope.textContent).not.toContain("W3");
  });

  it("says nothing at all where no record was read", async () => {
    const scope = await mount();

    expect(scope.textContent).not.toContain("Mixes:");
  });
});

// The lobby pin. `next-intl` is mocked to echo the key, so the options are read
// by position -- Auto first, then one per lobby the mix runs -- rather than by
// a label every option would share once the letter is interpolated away.
describe("PickupPlayerSheet lobby pin", () => {
  const pinOptions = (scope: ParentNode) => [
    ...scope.querySelectorAll('[role="radiogroup"][aria-label="Lobby for Aria#1111"] [role="radio"]'),
  ];

  it("offers no lobby pin while the mix runs one lobby", async () => {
    const scope = await mount(row());

    expect(scope.querySelector('[role="radiogroup"][aria-label="Lobby for Aria#1111"]')).toBeNull();
  });

  it("offers Auto plus one option per lobby the mix actually runs", async () => {
    // Six lobbies is the ceiling, so seven options is the widest this ever gets.
    expect(pinOptions(await mount(row(), null, 6))).toHaveLength(7);
  });

  it("pins the player to a lobby, and writes it with the rest of the patch", async () => {
    const scope = await mount(row(), null, 4);

    await act(async () => {
      // Auto, A, B, C, D -- so the fourth option is lobby C.
      pinOptions(scope)[3].dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });
    // Staged, like everything else in this sheet.
    expect(onSave).not.toHaveBeenCalled();

    await act(async () => {
      findButton(scope, "Save").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });

    expect(onSave.mock.calls[0][0]).toMatchObject({ lobby_pin: 2 });
  });

  it("sends no lobby pin at all from a one-lobby mix -- the server 422s it", async () => {
    const scope = await mount(row());

    await act(async () => {
      findButton(scope, "Save").dispatchEvent(new MouseEvent("click", { bubbles: true }));
      await tick();
    });

    expect(onSave.mock.calls[0][0]).not.toHaveProperty("lobby_pin");
  });

  it("shows the pin the server already stored", async () => {
    const scope = await mount(row({ lobby_pin: 3 }), null, 4);

    expect(pinOptions(scope)[4].getAttribute("aria-checked")).toBe("true");
    expect(pinOptions(scope)[1].getAttribute("aria-checked")).toBe("false");
  });
});

describe("PickupPlayerSheet away", () => {
  it("marks a player away, written only on Save", async () => {
    const scope = await mount();

    await click(scope.querySelector('[role="switch"][aria-label="Away"]') as Element);
    expect(onSave).not.toHaveBeenCalled();
    await click(findButton(scope, "Save"));

    expect(onSave.mock.calls[0][0]).toMatchObject({ away: true });
  });
});
