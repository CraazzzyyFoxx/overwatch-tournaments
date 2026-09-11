// @vitest-environment happy-dom
//
// This dialog is the only place in the mix tool where two lists have to agree
// with each other in real time — the workspace roster on the left, the lineup on
// the right — so what breaks here is the agreement, not the rendering. Pinned:
//
//  1. the seat counter and the role gauges read from the mix rows, and say
//     "over a full lobby" rather than silently showing an unbalanceable pool;
//  2. a row already in the mix offers Remove, not Add, so a host cannot add
//     somebody twice by rereading the page;
//  3. the keyboard path works without the pointer: the search field keeps focus,
//     the arrows move a cursor and Enter acts on it — the whole point of adding
//     twelve people in twelve keystrokes;
//  4. the "My ranks" filter narrows the server query to members this host has
//     personally rank-corrected, rather than everybody in the workspace;
//  5. ranks render read-only, dimmed when inherited from the workspace rather
//     than the host's own book -- editing them belongs to the roster sheet;
//  6. a read-only mix still reads the roster, membership does not change.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CustomGamePlayer } from "@/services/custom-game.service";
import type { RosterMember } from "@/services/workspace-player.service";

import { PickupAddPlayersDialog } from "./PickupAddPlayersDialog";

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
const summary = vi.fn();
const upsert = vi.fn();
const setRanks = vi.fn();
const listAuthors = vi.fn(async () => ({ authors: [] }));

vi.mock("@/services/workspace-player.service", () => ({
  workspacePlayerKeys: {
    all: (workspaceId: number) => ["workspace-players", workspaceId],
    list: (
      workspaceId: number,
      params: {
        page?: number;
        perPage?: number;
        query?: string;
        authorUserId?: number;
        authorOnly?: boolean;
      } = {},
    ) => [
      "workspace-players",
      workspaceId,
      params.page ?? 1,
      params.perPage ?? 30,
      params.query ?? "",
      params.authorUserId ?? 0,
      params.authorOnly ?? false,
    ],
    summary: (workspaceId: number, authorUserId?: number) => [
      "workspace-players",
      workspaceId,
      "summary",
      authorUserId ?? 0,
    ],
    authors: (workspaceId: number) => ["workspace-players", workspaceId, "authors"],
  },
  workspacePlayerService: {
    list: (...args: unknown[]) => list(...args),
    summary: (...args: unknown[]) => summary(...args),
    upsert: (...args: unknown[]) => upsert(...args),
    setRanks: (...args: unknown[]) => setRanks(...args),
    listAuthors: (...args: unknown[]) => listAuthors(...args),
  },
}));

vi.mock("@/services/custom-game.service", () => ({
  customGameKeys: {
    all: (workspaceId: number) => ["custom-games", workspaceId],
  },
}));

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/lib/notify", () => ({ notify: { success: vi.fn(), apiError: vi.fn() } }));
vi.mock("@/components/PlayerRoleIcon", () => ({ default: () => null }));
vi.mock("@/components/DivisionIcon", () => ({ default: () => null }));

const WORKSPACE_ID = 7;
/** Whose rank book this mix resolves against — the dialog must read that one. */
const HOST_USER_ID = 42;

function member(
  memberId: number,
  battleTag: string,
  overrides: Partial<RosterMember> = {},
): RosterMember {
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

function seated(memberId: number, battleTag: string, overrides: Partial<CustomGamePlayer> = {}) {
  return {
    id: memberId,
    workspace_member_id: memberId,
    display_name: null,
    battle_tag: battleTag,
    sort_order: memberId,
    participation: "pool",
    roles: ["tank"],
    ranks: { tank: 2400 },
    rank_sources: { tank: "workspace" as const },
    author_ranks: {},
    ...overrides,
  };
}

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

const onTogglePlayer = vi.fn();

async function mount(
  props: {
    rows?: CustomGamePlayer[];
    canEdit?: boolean;
    canEditRanks?: boolean;
    canWrite?: boolean;
    hostUserId?: number | null;
  } = {},
) {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    createRoot(container).render(
      <QueryClientProvider client={client}>
        <PickupAddPlayersDialog
          open
          onOpenChange={vi.fn()}
          workspaceId={WORKSPACE_ID}
          canEdit={props.canEdit ?? true}
          canEditRanks={props.canEditRanks ?? true}
          canWrite={props.canWrite ?? true}
          hostUserId={props.hostUserId ?? HOST_USER_ID}
          rows={props.rows ?? []}
          onTogglePlayer={onTogglePlayer}
        />
      </QueryClientProvider>,
    );
  });
  // The roster query and the chip-count summary query resolve after the first
  // commit; a second flush lets their state updates land inside `act`.
  await act(async () => {
    await tick();
  });
  // The dialog renders in a portal, so the assertions read the document.
  return document.body;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function key(node: Element | null | undefined, name: string) {
  if (!node) throw new Error("Expected a focusable node");
  return act(async () => {
    node.dispatchEvent(new KeyboardEvent("keydown", { key: name, bubbles: true }));
    await tick();
  });
}

function byLabel(label: string) {
  return document.body.querySelector<HTMLElement>(`[aria-label="${label}"]`);
}

function search() {
  return byLabel("Search the workspace roster") as HTMLInputElement;
}

/**
 * Types into a controlled field and drains the follow-up work: React only sees
 * the change through the prototype's value setter, and the deferred search value
 * re-renders once more after that.
 */
function type(value: string) {
  const input = search();
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
 * lower priority than the one `type` flushes.
 */
function settle() {
  return act(async () => {
    await tick();
    await tick();
  });
}

beforeEach(() => {
  document.body.innerHTML = "";
  vi.clearAllMocks();
  list.mockResolvedValue({
    results: [member(1, "Aria#1111"), member(2, "Borys#2222"), member(3, "Cleo#3333")],
    total: 3,
    page: 1,
    per_page: 24,
  });
  summary.mockResolvedValue({ total: 3, author_total: 1 });
});

describe("PickupAddPlayersDialog", () => {
  it("counts the lobby against a full one and names the overflow", async () => {
    const rows = Array.from({ length: 12 }, (_unused, index) =>
      seated(100 + index, `P${index}#1000`),
    );
    const scope = await mount({ rows });

    expect(scope.textContent).toContain("2 over a full lobby");
    // 12 tanks against a demand of 2, and nothing for the other two roles.
    expect(scope.textContent).toContain("12/2");
    expect(scope.textContent).toContain("0/4");
  });

  it("says how many more a lobby needs while it is short", async () => {
    const scope = await mount({ rows: [seated(1, "Aria#1111")] });

    expect(scope.textContent).toContain("9 more for a full lobby");
  });

  it("offers Remove for somebody already in the mix and Add for everyone else", async () => {
    await mount({ rows: [seated(2, "Borys#2222")] });

    expect(byLabel("Remove Borys#2222 from this mix")).not.toBeNull();
    expect(byLabel("Add Aria#1111 to this mix")).not.toBeNull();
    expect(byLabel("Add Borys#2222 to this mix")).toBeNull();
  });

  it("adds the row under the keyboard cursor without touching the pointer", async () => {
    await mount();

    // The cursor starts on the first row, so two downs land on the third.
    await key(search(), "ArrowDown");
    await key(search(), "ArrowDown");
    await key(search(), "Enter");

    expect(onTogglePlayer).toHaveBeenCalledWith(3);
  });

  it("keeps the cursor inside the list at both ends", async () => {
    await mount();

    await key(search(), "ArrowUp");
    await key(search(), "Enter");
    expect(onTogglePlayer).toHaveBeenCalledWith(1);

    onTogglePlayer.mockClear();
    for (let step = 0; step < 8; step += 1) {
      await key(search(), "ArrowDown");
    }
    await key(search(), "Enter");
    expect(onTogglePlayer).toHaveBeenCalledWith(3);
  });

  it("asks the server for only this host's ranked players under My ranks", async () => {
    const scope = await mount();

    await click(findChip(scope, "My ranks"));
    expect(list).toHaveBeenLastCalledWith(
      WORKSPACE_ID,
      expect.objectContaining({ authorOnly: true, authorUserId: HOST_USER_ID }),
    );

    await click(findChip(scope, "Everyone"));

    expect(list).toHaveBeenLastCalledWith(WORKSPACE_ID, expect.objectContaining({ authorOnly: false }));
  });

  it("shows both chip counts before either filter is clicked", async () => {
    const scope = await mount();

    expect(findChip(scope, "Everyone")?.textContent).toContain("3");
    expect(findChip(scope, "My ranks")?.textContent).toContain("1");
    expect(summary).toHaveBeenCalledWith(WORKSPACE_ID, HOST_USER_ID);
  });

  it("reads the host's book, not the caller's", async () => {
    await mount();

    // `author_ranks` in the response has to be the layer this mix balances on.
    // Defaulting to the caller's book is what used to make a co-organiser's
    // roster column disagree with the lineup rendered beside it.
    expect(list).toHaveBeenCalledWith(
      WORKSPACE_ID,
      expect.objectContaining({ authorUserId: HOST_USER_ID }),
    );
  });

  it("renders ranks read-only -- there is no control to write them from here", async () => {
    await mount();

    // No picker, no button: the crest is a plain span with a title, and the
    // dialog's only writes are `setRanks` (none) versus membership (still live).
    expect(byLabel("Tank rank for Aria#1111")).toBeNull();
    expect(document.body.querySelector('[title="Tank rank for Aria#1111"]')).not.toBeNull();
    expect(byLabel("Add Aria#1111 to this mix")?.hasAttribute("disabled")).toBe(false);
    expect(setRanks).not.toHaveBeenCalled();
  });

  it("clicking anywhere on the row adds or removes the player, not only the checkbox", async () => {
    const scope = await mount();

    // The name text sits well outside the small checkbox glyph -- the whole
    // row is the button now, so a click here still bubbles to it.
    await click(scope.querySelector('[title="Aria#1111"]'));

    expect(onTogglePlayer).toHaveBeenCalledWith(1);
  });

  it("shows an inherited workspace rank dimmed, rather than as an empty slot", async () => {
    list.mockResolvedValue({
      results: [member(1, "Aria#1111", { ranks: { tank: 2400 }, author_ranks: { dps: 2600 } })],
      total: 1,
      page: 1,
      per_page: 24,
    });
    await mount();

    // Inherited: the title says where the value came from, and it renders dimmed.
    const inherited = document.body.querySelector(
      '[title="Tank rank for Aria#1111, inherited 2400 from the workspace"]',
    );
    expect(inherited).not.toBeNull();
    expect(inherited?.className).toContain("opacity-45");
    // The host's own entry keeps the plain title and full opacity.
    const own = document.body.querySelector('[title="DPS rank for Aria#1111"]');
    expect(own).not.toBeNull();
    expect(own?.className).not.toContain("opacity-45");
  });

  it("locks membership on a closed mix", async () => {
    await mount({ canWrite: false, rows: [seated(2, "Borys#2222")] });

    expect(byLabel("Add Aria#1111 to this mix")?.hasAttribute("disabled")).toBe(true);
    expect(byLabel("Remove Borys#2222 from this mix")?.hasAttribute("disabled")).toBe(true);

    // Enter must not smuggle a write past the lock either.
    await key(search(), "Enter");
    expect(onTogglePlayer).not.toHaveBeenCalled();
  });

  it("separates an empty workspace from a search that matched nothing", async () => {
    list.mockResolvedValue({ results: [], total: 0, page: 1, per_page: 24 });
    const scope = await mount();
    expect(scope.textContent).toContain("No players in this workspace yet");

    await type("zzz");
    await settle();
    expect(scope.textContent).toContain("Nobody matches");
  });

  it("shows a dedicated empty state under My ranks", async () => {
    list.mockResolvedValue({ results: [], total: 0, page: 1, per_page: 24 });
    const scope = await mount();

    await click(findChip(scope, "My ranks"));

    expect(scope.textContent).toContain("You haven't ranked anyone yet");
  });


  it("offers a chip per author who has rank-corrected somebody, excluding the mix's own host", async () => {
    listAuthors.mockResolvedValueOnce({
      authors: [
        { user_id: HOST_USER_ID, display_name: "Host", count: 5 },
        { user_id: 501, display_name: "Ravi", count: 3 },
      ],
    });
    const scope = await mount();
    await settle();

    // The host already has "My ranks" -- listing them again would be the
    // same filter under a second label.
    expect(findChip(scope, "Host")).toBeUndefined();
    const ravi = findChip(scope, "Ravi");
    expect(ravi?.textContent).toContain("3");

    await click(ravi);
    expect(list).toHaveBeenLastCalledWith(
      WORKSPACE_ID,
      expect.objectContaining({ authorUserId: 501, authorOnly: true }),
    );
  });

  it("collapses authors beyond the visible cap into a +K more trigger", async () => {
    listAuthors.mockResolvedValueOnce({
      authors: Array.from({ length: 6 }, (_unused, index) => ({
        user_id: 500 + index,
        display_name: `Author${index}`,
        count: 1,
      })),
    });
    const scope = await mount();
    await settle();

    // 4 inline chips, 2 folded into the overflow trigger.
    expect(findChip(scope, "Author0")).not.toBeUndefined();
    expect(findChip(scope, "Author3")).not.toBeUndefined();
    expect(findChip(scope, "Author4")).toBeUndefined();
    expect(findChip(scope, "+2 more")).not.toBeUndefined();
  });
});

function findChip(scope: Element, label: string) {
  return [...scope.querySelectorAll("button")].find((node) => node.textContent?.includes(label));
}
