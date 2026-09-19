// @vitest-environment happy-dom
//
// The workspace roster is the one panel on the balancer page that talks to the
// network on its own, so the states around the happy path are what break in
// production. Pinned here:
//
//  1. "nothing here" and "nothing matched your search" are different messages,
//     and the second one offers the way back;
//  2. a failed request says so and offers a retry, instead of rendering the
//     empty state and telling an admin the workspace has no players;
//  3. the add field validates on submit rather than sitting behind a disabled
//     button, so the reason nothing happens is visible;
//  4. ranks are edited in the sheet, not in the row: the row's own crest pickers
//     could set a rank but never clear one, and cost every row three controls;
//  5. a write lands on the shared workspace canon, the only layer this panel
//     ever reads or writes -- a mix's own book has its own dialog instead.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RosterMember } from "@/services/workspace-player.service";

import { WorkspacePlayersSidebar } from "./WorkspacePlayersSidebar";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const list = vi.fn();
const upsert = vi.fn();
const setRanks = vi.fn();

vi.mock("@/services/workspace-player.service", () => ({
  workspacePlayerKeys: {
    all: (workspaceId: number) => ["workspace-players", workspaceId],
    list: (workspaceId: number, params: { page?: number; query?: string } = {}) => [
      "workspace-players",
      workspaceId,
      params.page ?? 1,
      params.query ?? "",
    ],
  },
  workspacePlayerService: {
    list: (...args: unknown[]) => list(...args),
    upsert: (...args: unknown[]) => upsert(...args),
    setRanks: (...args: unknown[]) => setRanks(...args),
  },
}));

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), apiError: vi.fn() } }));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));
// The sheet's live-rank card is a network read of its own and not what any of
// this pins.
vi.mock("@/components/RankHistory", () => ({ default: () => null }));
// The real rank controls are used as-is — the number field and Clear are the
// two things the row lost — so they need a grid to resolve divisions against.
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useDivisionGrid: () => ({
    tiers: [
      { number: 1, name: "Bronze", rank_min: 1000, rank_max: 1999, icon_url: "" },
      { number: 2, name: "Silver", rank_min: 2000, rank_max: 2999, icon_url: "" },
      { number: 3, name: "Gold", rank_min: 3000, rank_max: 3999, icon_url: "" },
    ],
  }),
}));

const WORKSPACE_ID = 7;

function member(memberId: number, battleTag: string, overrides: Partial<RosterMember> = {}): RosterMember {
  return {
    member_id: memberId,
    player_id: memberId * 10,
    battle_tag: battleTag,
    display_name: null,
    ranks: {},
    author_ranks: {},
    ...overrides,
  };
}

const ROSTER = [member(1, "Aria#1111"), member(2, "Borys#2222")];

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

/**
 * Every root this file mounts, so a test can be torn down by unmounting rather
 * than by wiping `document.body`. The sheet is portaled out of the panel, so
 * clearing the body under a still-mounted root left React trying to remove a
 * node that was no longer its child.
 */
const roots: Array<{ unmount: () => void }> = [];

async function unmountAll() {
  await act(async () => {
    for (const root of roots.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
}

async function mount(
  props: {
    canEdit?: boolean;
    collapsed?: boolean;
  } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const root = createRoot(container);
  roots.push(root);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <WorkspacePlayersSidebar
          workspaceId={WORKSPACE_ID}
          canEdit={props.canEdit ?? true}
          collapsed={props.collapsed ?? false}
        />
      </QueryClientProvider>,
    );
  });
  // The list query resolves after the first commit; a second flush lets its
  // state update land inside `act`.
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

/**
 * Types into a controlled field and drains the follow-up work: the deferred
 * search value re-renders once, and the query it triggers resolves after that.
 */
function type(input: HTMLInputElement, value: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  return act(async () => {
    setter?.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    await tick();
    await tick();
    await tick();
  });
}

/**
 * A second `act` pass: `useDeferredValue` schedules the search re-render at a
 * lower priority than the one `type` flushes, and the query it starts resolves
 * after that.
 */
function settle() {
  return act(async () => {
    await tick();
    await tick();
  });
}

/** Past the sheet's write delay, so a settled rank edit has had its chance to flush. */
function flushRankWrite() {
  return act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 500);
    await promise;
  });
}

function button(scope: Element, text: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.includes(text));
}

function field(scope: Element, label: string) {
  return scope.querySelector<HTMLInputElement>(`input[aria-label='${label}']`);
}

/** Radix portals the sheet, so its controls are a sibling of the panel. */
function openSheet(scope: Element, label: string) {
  return click(scope.querySelector(`button[title='Edit ${label}']`));
}

/** Every rank field in the open sheet, in render order: tank, damage, support. */
function rankFields() {
  return [...document.body.querySelectorAll<HTMLInputElement>('input[inputmode="numeric"]')];
}

function clearButtons() {
  return [...document.body.querySelectorAll("button")].filter(
    (node) => node.textContent?.trim() === "Clear",
  );
}

afterEach(async () => {
  await unmountAll();
});

beforeEach(() => {
  list.mockReset();
  upsert.mockReset();
  setRanks.mockReset();
  list.mockImplementation((_workspaceId: number, params: { query?: string }) => {
    const results = params.query ? [] : ROSTER;
    return Promise.resolve({ results, total: results.length, page: 1, per_page: 30 });
  });
  upsert.mockResolvedValue(member(3, "Cyrus#3333"));
  setRanks.mockResolvedValue({ ranks: {} });
});

describe("WorkspacePlayersSidebar", () => {
  it("separates an empty roster from a search that matched nothing, and offers the way back", async () => {
    const scope = await mount();
    const search = field(scope, "Search workspace players");
    if (!search) throw new Error("Expected the roster search field");

    await type(search, "zzz");
    await settle();

    expect(scope.textContent).toContain("No players match");
    expect(scope.textContent).toContain("zzz");
    // The single "No workspace players yet." message used to claim an empty
    // workspace whenever a query simply matched nothing.
    expect(scope.textContent).not.toContain("No workspace players yet");

    await click(button(scope, "Clear search"));
    await settle();

    expect(scope.textContent).toContain("Aria#1111");
    expect(search.value).toBe("");
  });

  it("reports a failed request with a retry instead of an empty roster", async () => {
    list.mockRejectedValue(new Error("offline"));

    const scope = await mount();

    expect(scope.textContent).toContain("Unable to load workspace players");
    expect(scope.textContent).not.toContain("No workspace players yet");
    expect(button(scope, "Retry")).toBeDefined();
  });

  it("keeps adding a player secondary and validates it on submit", async () => {
    const scope = await mount();

    // The permanent three-row form is gone: the panel is a roster first.
    expect(scope.querySelector("input[placeholder='Name#1234']")).toBeNull();

    await click(button(scope, "Add a workspace player"));

    // Radix portals the popover, so the form lives outside the panel subtree.
    const submit = button(document.body, "Add player");
    const battleTag = document.body.querySelector<HTMLInputElement>("input[placeholder='Name#1234']");
    if (!submit || !battleTag) throw new Error("Expected the add-player form");

    expect(submit.disabled).toBe(false);

    await click(submit);

    expect(upsert).not.toHaveBeenCalled();
    expect(document.body.textContent).toContain("Enter a BattleTag");
    expect(battleTag.getAttribute("aria-invalid")).toBe("true");

    await type(battleTag, "Cyrus#3333");
    await click(button(document.body, "Add player"));

    expect(upsert).toHaveBeenCalledWith(WORKSPACE_ID, "Cyrus#3333");
  });

  it("edits ranks in the sheet rather than in the row", async () => {
    const scope = await mount();

    // The row's three crest pickers are gone: they could set a rank and never
    // clear one, on every row whether or not anyone was editing it.
    expect(scope.querySelector("button[aria-label='Tank rank for Aria#1111']")).toBeNull();
    expect(rankFields()).toHaveLength(0);

    await openSheet(scope, "Aria#1111");

    // One field per role, and only for the player that was opened.
    expect(rankFields()).toHaveLength(3);
    expect(document.body.textContent).toContain("Roles and ranks");
  });

  it("never renders a lineup toggle: this panel keeps no selection of its own", async () => {
    const scope = await mount();
    const row = scope.querySelector("li");
    // The placeholder that held a toggle's place used to indent every row
    // against nothing -- the balancer page has no lineup to toggle into.
    expect(row?.className).toContain("grid-cols-1");
    expect(row?.querySelector("button[aria-label*='the lineup']")).toBeNull();
  });

  it("keeps the collapsed rail count honest while the first page is in flight", async () => {
    list.mockReturnValue(Promise.withResolvers<never>().promise);

    const scope = await mount({ collapsed: true });

    // `?? 0` used to render a confident "0" for every workspace during load.
    expect(scope.textContent).not.toMatch(/\d/);
    expect(scope.querySelector(".animate-pulse")).not.toBeNull();
  });

  it("stays the simplified pool row: no status, no exclude, no state chips", async () => {
    // Statuses and pool exclusion belong to a tournament registration, which a
    // workspace player does not have; both are already edited from the
    // registrations table. Re-adding them here would be a third copy.
    const scope = await mount();

    expect(scope.textContent).not.toMatch(/Exclude|Include in balancer|Ready|Flex/);
    expect(scope.querySelector("[data-slot='badge']")).toBeNull();
    // What the pool row does give it, and it keeps: role glyphs, the top rank
    // and a BattleTag copy control.
    expect(scope.querySelector("button[title='Copy BattleTag']")).not.toBeNull();
  });

  it("writes to the workspace layer, the only one this panel ever reads or writes", async () => {
    const scope = await mount();

    // The old caption promised the opposite of what the canon now does: it is a
    // fallback, not the rank a tournament balances on.
    expect(scope.textContent).not.toContain("carry across every tournament");

    await openSheet(scope, "Aria#1111");
    await type(rankFields()[0], "1200");
    await flushRankWrite();

    expect(setRanks).toHaveBeenLastCalledWith(WORKSPACE_ID, 1, {
      scope: "workspace",
      ranks: { tank: 1200 },
      clear: [],
    });
  });

  it("clears a rank off the layer instead of pinning a zero over it", async () => {
    list.mockImplementation(() =>
      Promise.resolve({
        results: [member(1, "Aria#1111", { ranks: { tank: 2500 } })],
        total: 1,
        page: 1,
        per_page: 30,
      }),
    );

    const scope = await mount();
    await openSheet(scope, "Aria#1111");

    // Only the role that has a value on this layer has anything to drop.
    const buttons = clearButtons();
    expect(buttons).toHaveLength(1);

    await click(buttons[0]);

    expect(setRanks).toHaveBeenLastCalledWith(WORKSPACE_ID, 1, {
      scope: "workspace",
      ranks: {},
      clear: ["tank"],
    });
  });

  it("locks the sheet of the member being saved rather than the roster behind it", async () => {
    setRanks.mockReturnValue(Promise.withResolvers<{ ranks: Record<string, number> }>().promise);
    list.mockImplementation(() =>
      Promise.resolve({
        results: [member(1, "Aria#1111", { ranks: { tank: 2500 } }), member(2, "Borys#2222")],
        total: 2,
        page: 1,
        per_page: 30,
      }),
    );

    const scope = await mount();
    await openSheet(scope, "Aria#1111");
    await click(clearButtons()[0]);

    expect(rankFields().every((node) => node.disabled)).toBe(true);
    // The roster behind the sheet is still readable and still openable.
    expect(scope.querySelector("button[title='Edit Borys#2222']")).not.toBeNull();
  });
});

