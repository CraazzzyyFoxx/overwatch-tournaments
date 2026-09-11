// @vitest-environment happy-dom
//
// The lineup keeps two things apart that one panel used to conflate: who is *in*
// the mix (membership, owned by the player pool) and who is *in the balance*
// (participation and commitment — must-play/pool/benched, this column's three
// drag-and-drop targets). Everything pinned here is a way that distinction can
// silently collapse, plus the pre-flight the panel exists to give a host:
//
//  1. a row's column IS its stored `participation`, and a drop writes that one
//     field without touching role order or ranks — otherwise "he's late"
//     quietly deletes his rank override;
//  2. removing is a separate control that does rewrite membership;
//  3. a role toggle writes the whole selection with the stored order left
//     alone — turning a role on appends it, off removes it, and neither
//     resorts the roles it did not touch;
//  4. the role-supply strip counts the way the solver does — a selected role with
//     no rank is not supply — and says which role is short before Balance runs;
//  5. Clear asks first, since it drops every per-mix override in the lobby;
//  6. the whole row opens the drawer, but a control inside it does NOT — that
//     containment is the only thing keeping "remove him" from also opening a
//     sheet over the lineup the host was reading;
//  7. a read-only viewer gets no write controls, no drag source and no drop
//     target, but can still read the setup.
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CustomGamePlayer,
  CustomGamePlayerPatch,
  RotationRecommendation,
} from "@/services/custom-game.service";

import { PickupLobbyPanel } from "./PickupLobbyPanel";

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
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
// Drag itself is not what this pins, and dnd-kit resolves its own React copy
// under pnpm (see PickupTeamsPanel.behavior.test.tsx), so it renders inertly
// here: children mount as plain DOM, no real drag/drop wiring. `DndContext`
// additionally captures `onDragEnd` so a test can invoke the bucket-mapping
// logic directly, the same way a real drop would.
const dndSpies = vi.hoisted(() => ({
  useDraggable: vi.fn(() => ({
    attributes: {},
    listeners: {},
    setNodeRef: () => {},
    isDragging: false,
  })),
  useDroppable: vi.fn(() => ({ setNodeRef: () => {}, isOver: false })),
  dragEndHandlers: [] as Array<(event: { active: { id: string }; over: { id: string } | null }) => void>,
}));
vi.mock("@dnd-kit/core", () => ({
  DndContext: ({
    children,
    onDragEnd,
  }: {
    children: React.ReactNode;
    onDragEnd?: (event: { active: { id: string }; over: { id: string } | null }) => void;
  }) => {
    if (onDragEnd) dndSpies.dragEndHandlers.push(onDragEnd);
    return children;
  },
  DragOverlay: () => null,
  PointerSensor: class {},
  useSensor: () => null,
  useSensors: () => [],
  useDraggable: dndSpies.useDraggable,
  useDroppable: dndSpies.useDroppable,
}));

const onPatchPlayer = vi.fn();
const onClear = vi.fn();
const onRemovePlayer = vi.fn();
const onOpenPlayer = vi.fn();
const onOpenPool = vi.fn();
const onApplyRotationHints = vi.fn();

function row(overrides: Partial<CustomGamePlayer> = {}): CustomGamePlayer {
  return {
    id: 1,
    workspace_member_id: 7,
    display_name: null,
    battle_tag: "Aria#1111",
    sort_order: 0,
    participation: "pool",
    roles: null,
    ranks: { tank: 2400, dps: 2600, support: 2500 },
    rank_sources: { tank: "workspace", dps: "workspace", support: "workspace" },
    author_ranks: {},
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount(
  rows: CustomGamePlayer[],
  props: {
    canWrite?: boolean;
    hasMix?: boolean;
    rotation?: RotationRecommendation[];
    applyingHints?: boolean;
  } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <PickupLobbyPanel
        canWrite={props.canWrite ?? true}
        hasMix={props.hasMix ?? true}
        rows={rows}
        rotation={props.rotation}
        savingPlayerId={null}
        clearing={false}
        onPatchPlayer={onPatchPlayer}
        onClear={onClear}
        onRemovePlayer={onRemovePlayer}
        onOpenPlayer={onOpenPlayer}
        onOpenPool={onOpenPool}
        onApplyRotationHints={onApplyRotationHints}
        applyingHints={props.applyingHints ?? false}
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

function byLabel(scope: ParentNode, label: string) {
  return scope.querySelector(`[aria-label="${label}"]`);
}

/** Icon-only controls carry their name in an `sr-only` span, not `aria-label`. */
function byName(scope: ParentNode, name: string) {
  return (
    [...scope.querySelectorAll("button")].find((node) => node.textContent?.trim() === name) ?? null
  );
}

function patchOf(playerId: number): CustomGamePlayerPatch {
  const call = onPatchPlayer.mock.calls.find(([id]) => id === playerId);
  if (!call) throw new Error(`No patch recorded for player ${playerId}`);
  return call[1] as CustomGamePlayerPatch;
}

/** Invokes the most recently rendered `DndContext.onDragEnd`, the same shape a real drop delivers. */
function dropOnto(memberId: number, bucketId: string | null) {
  const handler = dndSpies.dragEndHandlers[dndSpies.dragEndHandlers.length - 1];
  if (!handler) throw new Error("No onDragEnd handler captured");
  return act(async () => {
    handler({ active: { id: String(memberId) }, over: bucketId == null ? null : { id: bucketId } });
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  onPatchPlayer.mockReset();
  onClear.mockReset();
  onRemovePlayer.mockReset();
  onOpenPlayer.mockReset();
  onOpenPool.mockReset();
  onApplyRotationHints.mockReset();
  dndSpies.useDraggable.mockClear();
  dndSpies.useDroppable.mockClear();
  dndSpies.dragEndHandlers.length = 0;
});

describe("PickupLobbyPanel columns", () => {
  it("splits players into must-play, pool and benched columns", async () => {
    const scope = await mount([
      row({ participation: "must_play" }),
      row({ id: 2, workspace_member_id: 8, battle_tag: "Borys#2222" }),
      row({ id: 3, workspace_member_id: 9, battle_tag: "Cora#3333", participation: "benched" }),
    ]);

    expect(byLabel(scope, "Must play")?.textContent).toContain("Aria#1111");
    expect(byLabel(scope, "In the pool")?.textContent).toContain("Borys#2222");
    expect(byLabel(scope, "Benched")?.textContent).toContain("Cora#3333");
  });

  it("shows an empty hint in a column nothing has landed in yet", async () => {
    const scope = await mount([row()]);

    expect(byLabel(scope, "Must play")?.textContent).toContain("Drag a player here");
  });
});

describe("PickupLobbyPanel drag and drop", () => {
  it("wires every row as a drag source for a host who can write", async () => {
    await mount([row(), row({ id: 2, workspace_member_id: 8, battle_tag: "Borys#2222" })]);

    expect(dndSpies.useDraggable).toHaveBeenCalledTimes(2);
    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: false });
    }
  });

  it("disables both the drag source and the drop targets for a read-only viewer", async () => {
    await mount([row()], { canWrite: false });

    for (const call of dndSpies.useDraggable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: true });
    }
    for (const call of dndSpies.useDroppable.mock.calls) {
      expect(call[0]).toMatchObject({ disabled: true });
    }
  });

  it("guarantees a seat on a drop into Must play, writing both fields at once", async () => {
    await mount([row()]);

    await dropOnto(7, "must_play");

    expect(patchOf(7)).toEqual({ participation: "must_play" });
  });

  it("benches on a drop into Benched, clearing a stale must-play pin too", async () => {
    await mount([row({ participation: "must_play" })]);

    await dropOnto(7, "benched");

    expect(patchOf(7)).toEqual({ participation: "benched" });
  });

  it("returns a benched player to the pool on a drop back into it", async () => {
    await mount([row({ participation: "benched" })]);

    await dropOnto(7, "pool");

    expect(patchOf(7)).toEqual({ participation: "pool" });
  });

  it("does nothing when a row is dropped back onto its own column", async () => {
    await mount([row()]);

    await dropOnto(7, "pool");

    expect(onPatchPlayer).not.toHaveBeenCalled();
  });

  it("does nothing when a row is dropped outside every column", async () => {
    await mount([row()]);

    await dropOnto(7, null);

    expect(onPatchPlayer).not.toHaveBeenCalled();
  });
});

describe("PickupLobbyPanel rotation hints", () => {
  it("marks a member owed a seat with an amber hint carrying the reason", async () => {
    const scope = await mount([row()], {
      rotation: [
        {
          workspace_member_id: 7,
          status: "must_play",
          reason: "Sat 1 map(s) in a row \u2014 owed a seat",
          consecutive_sat: 1,
          consecutive_played: 0,
          games_played: 2,
        },
      ],
    });

    const badge = scope.querySelector('[title="Sat 1 map(s) in a row \u2014 owed a seat"]');
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toContain("Sat 1 map(s) in a row \u2014 owed a seat");
  });

  it("marks a member who has played the most in a row with a should-rest hint", async () => {
    const scope = await mount([row()], {
      rotation: [
        {
          workspace_member_id: 7,
          status: "should_rest",
          reason: "Played 3 map(s) in a row",
          consecutive_sat: 0,
          consecutive_played: 3,
          games_played: 3,
        },
      ],
    });

    expect(scope.querySelector('[title="Played 3 map(s) in a row"]')).not.toBeNull();
  });

  it("renders no hint for a row already pinned must_play -- the Pin already says it", async () => {
    const scope = await mount([row({ participation: "must_play" })], {
      rotation: [
        {
          workspace_member_id: 7,
          status: "must_play",
          reason: "Закреплён хостом (must_play)",
          consecutive_sat: 0,
          consecutive_played: 2,
          games_played: 2,
        },
      ],
    });

    expect(scope.querySelector('[title="Закреплён хостом (must_play)"]')).toBeNull();
  });

  it("renders no hint for a neutral verdict or when no rotation data has loaded", async () => {
    const neutral = await mount([row()], {
      rotation: [
        {
          workspace_member_id: 7,
          status: "neutral",
          reason: "Seats cover the whole pool",
          consecutive_sat: 0,
          consecutive_played: 0,
          games_played: 0,
        },
      ],
    });
    expect(neutral.textContent).not.toContain("Seats cover the whole pool");

    const noData = await mount([row()]);
    expect(noData.querySelector('[title*="owed a seat"]')).toBeNull();
  });
});

describe("PickupLobbyPanel apply hints button", () => {
  it("is absent until rotation data has loaded", async () => {
    const scope = await mount([row()]);
    expect(byName(scope, "Apply rotation hints")).toBeNull();
  });

  it("is disabled once loaded but nothing needs to change", async () => {
    const scope = await mount([row({ participation: "pool" })], {
      rotation: [
        {
          workspace_member_id: 7,
          status: "neutral",
          reason: "",
          consecutive_sat: 0,
          consecutive_played: 0,
          games_played: 0,
        },
      ],
    });
    const button = byName(scope, "Apply rotation hints");
    expect(button).not.toBeNull();
    expect(button?.hasAttribute("disabled")).toBe(true);
  });

  it("applies every actionable hint on click", async () => {
    const scope = await mount([row({ participation: "benched" })], {
      rotation: [
        {
          workspace_member_id: 7,
          status: "must_play",
          reason: "Owed a seat",
          consecutive_sat: 1,
          consecutive_played: 0,
          games_played: 2,
        },
      ],
    });
    const button = byName(scope, "Apply rotation hints");
    expect(button?.hasAttribute("disabled")).toBe(false);

    await click(button);
    expect(onApplyRotationHints).toHaveBeenCalledTimes(1);
  });
});

describe("PickupLobbyPanel", () => {
  it("removes a player through its own control, not through a drag", async () => {
    const scope = await mount([row()]);

    await click(byName(scope, "Remove Aria#1111 from this mix"));

    expect(onRemovePlayer).toHaveBeenCalledWith(7);
    expect(onPatchPlayer).not.toHaveBeenCalled();
  });

  it("writes the whole selection when a role is toggled, preserving the stored order", async () => {
    // `roles: null` is "not configured"; the panel must not leave the rest of the
    // selection to a server-side default once the host has touched it.
    const scope = await mount([row({ roles: null })]);

    await click(byLabel(scope, "Tank for Aria#1111, first choice, 2400 points"));

    expect(patchOf(7)).toEqual({ roles: ["dps", "support"] });
  });

  it("appends a switched-on role to the end of the stored order, not by its rank", async () => {
    // Support (2500) outranks the already-selected tank (2400), but turning it
    // on must not jump it in front — the host's order for tank is left alone.
    const scope = await mount([row({ roles: ["tank"] })]);

    await click(byLabel(scope, "Support for Aria#1111, off, 2500 points"));

    expect(patchOf(7)).toEqual({ roles: ["tank", "support"] });
  });

  it("names which role the balancer will seat first from the stored order, not the rank", async () => {
    // The order was stored tank-dps-support; ranks say dps is strongest, but
    // the rail shows what the host set, not what the ranks would pick.
    const scope = await mount([row({ roles: ["tank", "dps", "support"] })]);

    expect(byLabel(scope, "Tank for Aria#1111, first choice, 2400 points")).not.toBeNull();
    expect(byLabel(scope, "DPS for Aria#1111, also plays, 2600 points")).not.toBeNull();
    expect(byLabel(scope, "Support for Aria#1111, also plays, 2500 points")).not.toBeNull();
  });

  it("freezes the role rail for a benched row, but not for pool or must-play", async () => {
    const scope = await mount([
      row({ roles: ["tank"] }),
      row({ id: 2, workspace_member_id: 8, battle_tag: "Borys#2222", roles: ["tank"], participation: "benched" }),
    ]);

    expect(
      byLabel(scope, "Tank for Aria#1111, first choice, 2400 points")?.hasAttribute("disabled"),
    ).toBe(false);
    expect(
      byLabel(scope, "Tank for Borys#2222, first choice, 2400 points")?.hasAttribute("disabled"),
    ).toBe(true);
  });

  it("counts role supply the way the solver does, not the way the chips look", async () => {
    // Tank is selected but unranked, so it is not supply: 5v5 wants 2 tanks and
    // this lineup can seat none.
    const scope = await mount([
      row({ roles: ["tank", "dps"], ranks: { dps: 2600 } }),
      row({
        id: 2,
        workspace_member_id: 8,
        battle_tag: "Borys#2222",
        roles: ["dps"],
        ranks: { dps: 2500 },
      }),
    ]);

    expect(scope.textContent).toContain("0 of 2 · short 2");
    expect(scope.textContent).toContain("2 of 4");
  });

  it("warns once every selected role of an active player is unranked", async () => {
    const scope = await mount([row({ roles: ["tank"], ranks: { dps: 2600 } })]);

    expect(scope.textContent).toContain("1 player has no ranked role");
  });

  it("opens the player sheet from the row, but not from a role click", async () => {
    const scope = await mount([row()]);

    // The whole row is the target; a role chip inside it must not ride along.
    await click(byLabel(scope, "In the pool")?.querySelector("li"));
    expect(onOpenPlayer).toHaveBeenCalledWith(7);

    onOpenPlayer.mockClear();
    await click(byLabel(scope, "Tank for Aria#1111, first choice, 2400 points"));
    expect(onPatchPlayer).toHaveBeenCalled();
  });

  it("keeps the settings control reachable without a pointer", async () => {
    // The row's own click is a pointer affordance; the button is what a keyboard
    // reaches, so it has to stay even when nothing else on the row is writable.
    const scope = await mount([row()], { canWrite: false });

    expect(byName(scope, "Advanced settings for Aria#1111")).not.toBeNull();
  });

  it("hands adding players back to the pool", async () => {
    const scope = await mount([row()]);

    await click(byName(scope, "Add players →"));

    expect(onOpenPool).toHaveBeenCalledTimes(1);
  });

  it("confirms before emptying the lobby", async () => {
    const scope = await mount([
      row(),
      row({ id: 2, workspace_member_id: 8, battle_tag: "Borys#2222" }),
    ]);

    await click(byName(scope, "Empty the lobby"));
    expect(onClear).not.toHaveBeenCalled();

    expect(document.querySelector('[role="alertdialog"]')?.textContent).toContain(
      "removes all 2 players",
    );

    await click(byName(document, "Remove everyone"));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("separates no mix from an empty lineup", async () => {
    const withoutMix = await mount([], { hasMix: false });
    expect(withoutMix.textContent).toContain("No mix selected");

    document.body.innerHTML = "";
    const empty = await mount([]);
    expect(empty.textContent).toContain("Lineup is empty");
  });

  it("hides every write control for a read-only viewer", async () => {
    const scope = await mount([row()], { canWrite: false });

    expect(byName(scope, "Empty the lobby")).toBeNull();
    expect(byName(scope, "Add players →")).toBeNull();
    expect(byName(scope, "Remove Aria#1111 from this mix")).toBeNull();
    expect(
      byLabel(scope, "Tank for Aria#1111, first choice, 2400 points")?.hasAttribute("disabled"),
    ).toBe(true);
  });

  it("opens the drawer from anywhere on the card", async () => {
    const scope = await mount([row()]);

    await click(scope.querySelector('li[title*="Aria#1111"]'));

    expect(onOpenPlayer).toHaveBeenCalledWith(7);
    expect(onPatchPlayer).not.toHaveBeenCalled();
  });

  it("keeps the row's own controls from opening the drawer", async () => {
    // The wrappers that stop propagation are the whole point: without them the
    // sheet lands on top of the lineup every time a host clears a role.
    const scope = await mount([row()]);

    await click(byLabel(scope, "Tank for Aria#1111, first choice, 2400 points"));
    await click(byName(scope, "Remove Aria#1111 from this mix"));

    expect(onPatchPlayer).toHaveBeenCalled();
    expect(onRemovePlayer).toHaveBeenCalledWith(7);
    expect(onOpenPlayer).not.toHaveBeenCalled();
  });
});
