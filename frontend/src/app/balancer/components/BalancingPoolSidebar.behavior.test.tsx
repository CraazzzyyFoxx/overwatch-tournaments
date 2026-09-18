// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { BalancerApplication, BalancerPlayerRecord } from "@/types/balancer-admin.types";
import type { PlayerValidationState } from "./balancer-page-helpers";
import { BalancingPoolSidebar } from "./BalancingPoolSidebar";

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
// The board is a closed dnd-kit dialog here; inlining it would load a second React copy under pnpm.
vi.mock("./PoolTriageBoard", () => ({ PoolTriageBoard: () => null }));

function player(id: number, battleTag: string, overrides: Partial<BalancerPlayerRecord> = {}): BalancerPlayerRecord {
  return {
    id,
    tournament_id: 80,
    application_id: id,
    battle_tag: battleTag,
    battle_tag_normalized: battleTag.toLowerCase(),
    user_id: id,
    role_entries_json: [
      { role: "support", subtype: null, priority: 1, division_number: 12, rank_value: 900, is_active: true, is_declared_active: true, ow_rank_value: null },
    ],
    is_flex: false,
    is_in_pool: true,
    admin_notes: null,
    ...overrides,
  };
}

function application(id: number, battleTag: string): BalancerApplication {
  return {
    id,
    tournament_id: 80,
    tournament_sheet_id: 1,
    battle_tag: battleTag,
    battle_tag_normalized: battleTag.toLowerCase(),
    smurf_tags_json: [],
    twitch_nick: null,
    discord_nick: null,
    stream_pov: false,
    last_tournament_text: null,
    primary_role: "damage",
    additional_roles_json: [],
    notes: null,
    submitted_at: null,
    synced_at: "2026-03-14T00:00:00Z",
    is_active: true,
    player: null,
  };
}

const POOL_STATES: PlayerValidationState[] = [
  { player: player(1, "Aria#1111"), issues: [] },
  { player: player(2, "Borys#2222"), issues: [] },
  {
    player: player(3, "Cyrus#3333", { role_entries_json: [] }),
    issues: [{ code: "missing_ranked_role", message: "No ranked roles configured" }],
  },
];

const AVAILABLE = [application(90, "Dita#9090"), application(91, "Egor#9191")];

const onSelectPlayer = vi.fn();
const onAddFromApplication = vi.fn();

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  await act(async () => {
    createRoot(container).render(
      <BalancingPoolSidebar
        allPlayerValidationStates={POOL_STATES}
        applications={AVAILABLE}
        addableApplications={AVAILABLE}
        selectedPlayerId={null}
        onSelectPlayer={onSelectPlayer}
        onAddFromApplication={onAddFromApplication}
        isAddingPlayer={false}
      />,
    );
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

function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
  });
}

function searchInput(scope: Element) {
  return scope.querySelector<HTMLInputElement>("input[aria-label='Search the Balancing Pool']");
}

function pill(scope: Element, label: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.startsWith(label));
}

beforeEach(() => {
  document.body.innerHTML = "";
  onSelectPlayer.mockReset();
  onAddFromApplication.mockReset();
});

describe("BalancingPoolSidebar", () => {
  it("filters the one visible list instead of opening a second results surface", async () => {
    const scope = await mount();
    const input = searchInput(scope);
    if (!input) throw new Error("Expected the pool search field");

    await type(input, "Borys");

    expect(scope.textContent).toContain("Borys#2222");
    expect(scope.textContent).not.toContain("Aria#1111");
    // The removed popover announced its own result header above the list it had just filtered.
    expect(scope.textContent).not.toContain("Quick results");
    expect(scope.querySelectorAll("input[aria-label='Search the Balancing Pool']")).toHaveLength(1);
  });

  it("reaches available registrations through a filter pill and keeps the search applied", async () => {
    const scope = await mount();
    const input = searchInput(scope);
    if (!input) throw new Error("Expected the pool search field");

    await type(input, "Egor");
    await click(pill(scope, "Available"));

    expect(scope.textContent).toContain("Egor#9191");
    expect(scope.textContent).not.toContain("Dita#9090");
    // The old "Pool / Add" mode toggle duplicated this pill and wiped the query on switch.
    expect(input.value).toBe("Egor");
    expect(pill(scope, "Add")).toBeUndefined();
  });

  it("exposes the active filter as pressed state rather than colour alone", async () => {
    const scope = await mount();

    expect(pill(scope, "All")?.getAttribute("aria-pressed")).toBe("true");
    expect(pill(scope, "Ready")?.getAttribute("aria-pressed")).toBe("false");

    await click(pill(scope, "Ready"));

    expect(pill(scope, "Ready")?.getAttribute("aria-pressed")).toBe("true");
    expect(pill(scope, "All")?.getAttribute("aria-pressed")).toBe("false");
  });

  it("spends a row on bulk actions only once something is selected", async () => {
    const scope = await mount();

    expect(scope.textContent).not.toContain("Select players for bulk actions");
    expect(scope.textContent).not.toContain("selected");

    await click(scope.querySelector("[aria-label='Select Aria#1111']"));

    expect(scope.textContent).toContain("1 selected");
    expect(scope.textContent).toContain("Select all 3");
  });

  it("opens the player editor from a keyboard-reachable control", async () => {
    const scope = await mount();
    const nameButton = [...scope.querySelectorAll("button")].find((node) =>
      node.getAttribute("title") === "Edit Aria#1111",
    );

    await click(nameButton);

    expect(onSelectPlayer).toHaveBeenCalledWith(1);
  });
});
