// @vitest-environment happy-dom
//
// The player's own corner of a mix board. Four things are load-bearing:
//
//  1. a blocker that only an account link can fix offers the link, because the
//     player cannot discover "go link Battle.net" from a refusal alone;
//  2. `can_edit_roles=false` shows the roles and edits nothing -- the host's
//     mix is the host's, and a disabled editor must not be a lie;
//  3. Save writes the drag order and the flex flag, and nothing else: ranks are
//     the host's book (`MIX_ORDER`), participation is the host's decision;
//  4. leaving is always offered to somebody on the roster, even while every
//     other action is blocked -- an unlinked account must still be able to go.
//
// `next-intl` is mocked to echo the key, so every label asserted below is the
// message key rather than the rendered sentence.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { MixSelfSeat, MixSelfState } from "@/services/custom-game.service";

import { PickupMySeatPanel } from "./PickupMySeatPanel";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
// Drag itself is not what this pins, and dnd-kit resolves its own React copy
// under bun/node, so the sortable wrapper and its hook render inertly here.
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

const openSettings = vi.fn();
vi.mock("@/stores/account-settings-modal.store", () => ({
  useAccountSettingsModalStore: (selector: (state: { open: (tab?: string) => void }) => unknown) =>
    selector({ open: openSettings }),
}));

const onJoin = vi.fn();
const onLeave = vi.fn();
const onSave = vi.fn();

function seat(overrides: Partial<MixSelfSeat> = {}): MixSelfSeat {
  return {
    participation: "pool",
    roles: ["tank", "damage"],
    is_flex: false,
    ranks: { tank: 3300, damage: 2700, support: null },
    ...overrides,
  };
}

function state(overrides: Partial<MixSelfState> = {}): MixSelfState {
  return {
    custom_game_id: 12,
    name: "Thursday scrim",
    status: "balanced",
    self_signup: "pool",
    self_role_edit: true,
    seat: seat(),
    unranked_roles: [],
    policy: {
      can_join: false,
      can_leave: true,
      can_edit_roles: true,
      join_blocker: "already_joined",
      edit_blocker: null,
    },
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

const roots: { unmount: () => void }[] = [];

async function mount(value: MixSelfState) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    const root = createRoot(container);
    roots.push(root);
    root.render(
      <PickupMySeatPanel
        state={value}
        saving={false}
        onJoin={onJoin}
        onLeave={onLeave}
        onSave={onSave}
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
  return (
    [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null
  );
}

beforeEach(() => {
  while (roots.length > 0) {
    const root = roots.pop();
    act(() => root?.unmount());
  }
  document.body.innerHTML = "";
  openSettings.mockReset();
  onJoin.mockReset();
  onLeave.mockReset();
  onSave.mockReset();
});

describe("PickupMySeatPanel blockers", () => {
  it("offers account settings when only a link is missing", async () => {
    const scope = await mount(
      state({
        seat: null,
        policy: {
          can_join: false,
          can_leave: false,
          can_edit_roles: false,
          join_blocker: "battlenet_not_linked",
          edit_blocker: "battlenet_not_linked",
        },
      }),
    );

    expect(scope.textContent).toContain("blocker.battlenet_not_linked");
    await click(byName(scope, "fixLinks"));

    expect(openSettings).toHaveBeenCalledWith("profile");
  });

  it("offers no account settings for a blocker linking cannot fix", async () => {
    const scope = await mount(
      state({
        seat: null,
        policy: {
          can_join: false,
          can_leave: false,
          can_edit_roles: false,
          join_blocker: "signup_closed",
          edit_blocker: "not_on_roster",
        },
      }),
    );

    expect(scope.textContent).toContain("blocker.signup_closed");
    expect(byName(scope, "fixLinks")).toBeNull();
  });

  it("still lets an unlinked player on the roster leave", async () => {
    const scope = await mount(
      state({
        policy: {
          can_join: false,
          can_leave: true,
          can_edit_roles: false,
          join_blocker: "battlenet_not_linked",
          edit_blocker: "battlenet_not_linked",
        },
      }),
    );

    await click(byName(scope, "leave"));

    expect(onLeave).toHaveBeenCalledTimes(1);
  });

  it("joins when the policy allows it", async () => {
    const scope = await mount(
      state({
        seat: null,
        policy: {
          can_join: true,
          can_leave: false,
          can_edit_roles: false,
          join_blocker: null,
          edit_blocker: "not_on_roster",
        },
      }),
    );

    await click(byName(scope, "join"));

    expect(onJoin).toHaveBeenCalledTimes(1);
  });
});

describe("PickupMySeatPanel roles", () => {
  it("edits nothing while the host keeps role editing to themselves", async () => {
    const scope = await mount(
      state({
        self_role_edit: false,
        policy: {
          can_join: false,
          can_leave: true,
          can_edit_roles: false,
          join_blocker: "already_joined",
          edit_blocker: "role_edit_off",
        },
      }),
    );

    // The roles are still readable -- the mix is theirs to read either way.
    expect(scope.textContent).toContain("Tank");
    expect(scope.textContent).toContain("blocker.role_edit_off");
    expect(byName(scope, "saveRoles")).toBeNull();
    expect([...scope.querySelectorAll('[role="switch"]')].every((node) => node.hasAttribute("disabled"))).toBe(
      true,
    );
  });

  it("writes only the role order and the flex flag", async () => {
    const scope = await mount(state());

    await click(scope.querySelector('[aria-label="Support for you"]'));
    await click(scope.querySelector('[aria-label="Full flex for you"]'));
    await click(byName(scope, "saveRoles"));

    expect(onSave).toHaveBeenCalledWith({ roles: ["tank", "damage", "support"], is_flex: true });
  });

  it("never edits a rank", async () => {
    const scope = await mount(state());

    expect(scope.querySelectorAll('input[inputmode="numeric"]')).toHaveLength(0);
    expect(scope.textContent).toContain("3300");
  });

  it("warns about a role no rank answers for", async () => {
    const scope = await mount(state({ unranked_roles: ["support"] }));

    expect(scope.textContent).toContain("unranked");
  });
});
