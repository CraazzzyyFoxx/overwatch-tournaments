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
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGamePlayer, MixMemberStats } from "@/services/custom-game.service";

import { PickupPlayerSheet } from "./PickupPlayerSheet";

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
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
vi.mock("@/components/RankHistory", () => ({ default: () => null }));
// Drag itself is not what this pins, and dnd-kit resolves its own React copy
// under pnpm, so the sortable wrapper and its hook render inertly here.
vi.mock("@/app/balancer/components/SortableRows", () => ({
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
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useDivisionGrid: () => ({
    tiers: [
      { number: 1, name: "Bronze", rank_min: 1000, rank_max: 1999, icon_url: "" },
      { number: 2, name: "Silver", rank_min: 2000, rank_max: 2999, icon_url: "" },
      { number: 3, name: "Gold", rank_min: 3000, rank_max: 3999, icon_url: "" },
    ],
  }),
}));

const onSave = vi.fn();
const onOpenChange = vi.fn();
const onRemove = vi.fn();

function row(overrides: Partial<CustomGamePlayer> = {}): CustomGamePlayer {
  return {
    id: 1,
    workspace_member_id: 7,
    display_name: null,
    battle_tag: "Aria#1111",
    sort_order: 0,
    participation: "pool",
    roles: ["tank", "dps"],
    ranks: { tank: 3300, dps: 2700, support: 2900 },
    rank_sources: { tank: "author", dps: "workspace", support: "ow" },
    author_ranks: { tank: 3300 },
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
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupPlayerSheet
        row={value}
        mixStats={mixStats}
        canEdit
        saving={false}
        onOpenChange={onOpenChange}
        onSave={onSave}
        onRemove={onRemove}
      />,
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
      roles: ["tank", "dps"],
      is_flex: false,
    });
    expect(rankChange).toEqual({ ranks: { dps: 3000 }, clear: [] });
  });

  it("offers Clear only where the host has an entry of their own, and stages it for Save", async () => {
    const scope = await mount();

    // Tank alone comes from the author's own book; dps/support are inherited, so
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

  // balancer-service resolves a mix's ranks against the GLOBAL, OW-synced grid
  // (`get_effective_division_grid(session, None)` -> the grid with
  // `workspace_id IS NULL`), never the host workspace's. The mocked workspace
  // grid above deliberately disagrees: it calls 3300 "Gold" where the OW ladder
  // calls it "Diamond 2". Reading the workspace grid here renamed a number the
  // backend had already fixed, so the crest and label disagreed with the mix
  // the solver actually balanced.
  it("labels ranks with the global OW ladder, not the workspace's grid", async () => {
    const scope = await mount();

    expect(scope.textContent).toContain("Diamond 2");
    expect(scope.textContent).not.toContain("Gold");
  });
});

describe("PickupPlayerSheet priority", () => {
  it("keeps the host's stored role order instead of re-sorting by rank", async () => {
    // Stored order says dps-then-tank; the ranks say the opposite (tank
    // outranks dps). The order shown, and the order Save writes, must stay
    // exactly what the host stored.
    const scope = await mount(
      row({ roles: ["dps", "tank"], ranks: { tank: 3300, dps: 2700, support: 2900 } }),
    );

    expect(rankFields(scope).map((node) => node.value)).toEqual(["2700", "3300", "2900"]);

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch.roles).toEqual(["dps", "tank"]);
  });

  it("appends a role turned on to the end of the order, not a rank-sorted slot", async () => {
    // Support outranks both selected roles, but switching it on must not jump
    // it to the front.
    const scope = await mount(
      row({ roles: ["tank", "dps"], ranks: { tank: 2000, dps: 2700, support: 4000 } }),
    );

    const supportSwitch = scope.querySelector<HTMLElement>('[aria-label="Support for Aria#1111"]');
    if (!supportSwitch) throw new Error("Support switch not found");
    await click(supportSwitch);

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch.roles).toEqual(["tank", "dps", "support"]);
  });

  it("drops a role turned off from the order without touching the rest", async () => {
    const scope = await mount(row({ roles: ["tank", "dps"] }));

    const tankSwitch = scope.querySelector<HTMLElement>('[aria-label="Tank for Aria#1111"]');
    if (!tankSwitch) throw new Error("Tank switch not found");
    await click(tankSwitch);

    await click(findButton(scope, "Save"));
    const [patch] = onSave.mock.calls[0];
    expect(patch.roles).toEqual(["dps"]);
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
      battle_tag: "Aria#1111",
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
