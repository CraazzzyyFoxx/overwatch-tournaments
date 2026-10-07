// @vitest-environment happy-dom
//
// The two pieces of this table that are not the shared `DataTable`:
//  1. a fixed `playerId` drops the player column AND the search box — both only
//     answer "which person", which the person page already settled;
//  2. the division chips are the rank-range filter, mapped through the
//     workspace grid, and the top tier is open-ended (`rank_max: null`), which
//     means "no ceiling" rather than "max 0".
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RankOverviewTable } from "@/components/admin/ranks/RankOverviewTable";
import type { RankOverviewListParams, RankOverviewRow } from "@/services/workspace-player.service";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/ranks",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

// Message keys, not copy: every assertion is about which fact reaches the row.
vi.mock("next-intl", () => ({
  useTranslations: () =>
    Object.assign((key: string) => key, { has: () => true, rich: (key: string) => key })
}));

vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));

// The grid the division chips are mapped through. Gold is open-ended, which is
// the case the range mapping gets wrong if it reads `rank_max` as a number.
vi.mock("@/hooks/useCurrentWorkspace", () => ({
  useDivisionGrid: () => ({
    tiers: [
      { number: 1, name: "Bronze", rank_min: 500, rank_max: 999, icon_url: "" },
      { number: 2, name: "Silver", rank_min: 1000, rank_max: 1499, icon_url: "" },
      { number: 3, name: "Gold", rank_min: 1500, rank_max: null, icon_url: "" }
    ]
  })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 7 })
}));

const listRanks = vi.fn();
const listAuthors = vi.fn();

vi.mock("@/services/workspace-player.service", async (importOriginal) => {
  // The constants (`RANK_LAYERS`, roles) stay real; only the two reads are stubbed.
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    workspacePlayerService: {
      listRanks: (...args: unknown[]) => listRanks(...args),
      listAuthors: (...args: unknown[]) => listAuthors(...args)
    }
  };
});

function row(overrides: Partial<RankOverviewRow> = {}): RankOverviewRow {
  return {
    layer: "canon",
    player_id: 42,
    member_id: 9,
    display_name: "Alice",
    battle_tag: "Alice#2100",
    author_user_id: null,
    author_name: null,
    role: "tank",
    rank_value: 3100,
    division: 2,
    source: null,
    sigma: null,
    delta: null,
    canon_diff: null,
    ow_division: null,
    ow_tier: null,
    context: null,
    at: "2026-01-02T03:04:05Z",
    ...overrides
  };
}

let container: HTMLElement;
let root: Root;

function lastParams(): RankOverviewListParams {
  return listRanks.mock.calls.at(-1)?.[1] as RankOverviewListParams;
}

async function render(search: string, playerId?: number) {
  window.history.replaceState(null, "", `/admin/ranks${search}`);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <RankOverviewTable playerId={playerId} />
      </QueryClientProvider>
    );
  });
  // The page query resolves a macrotask later; without this the body is still
  // the loading skeleton and every row assertion reads an empty table.
  await act(async () => {
    const settled = Promise.withResolvers<void>();
    setTimeout(settled.resolve, 0);
    await settled.promise;
  });
}

beforeEach(() => {
  listRanks.mockReset();
  listRanks.mockResolvedValue({ page: 1, per_page: 30, total: 1, results: [row()] });
  listAuthors.mockReset();
  listAuthors.mockResolvedValue({ authors: [] });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("rank overview table", () => {
  it("drops the player column and the search box when pinned to one person", async () => {
    await render("", 42);

    const headers = [...container.querySelectorAll("th")].map((cell) => cell.textContent);
    expect(headers).not.toContain("columns.player");
    expect(headers).toContain("columns.layer");
    expect(container.querySelector('input[name="admin-table-search"]')).toBeNull();
    expect(lastParams().playerId).toBe(42);
  });

  it("links the player to their person page when not pinned", async () => {
    await render("");

    const headers = [...container.querySelectorAll("th")].map((cell) => cell.textContent);
    expect(headers).toContain("columns.player");
    expect(container.querySelector('a[href="/admin/people/42"]')).not.toBeNull();
    expect(lastParams().playerId).toBeUndefined();
  });

  it("turns the division chips into a rank range on the workspace grid", async () => {
    await render("?div_min=1&div_max=2");

    expect(lastParams().rankMin).toBe(500);
    expect(lastParams().rankMax).toBe(1499);
  });

  it("leaves the range open-ended when the top division has no ceiling", async () => {
    await render("?div_min=2&div_max=3");

    expect(lastParams().rankMin).toBe(1000);
    expect(lastParams().rankMax).toBeUndefined();
  });

  it("passes the layer, author and canon-diff filters the URL carries", async () => {
    await render("?layer=author,ow&author=5,8&role=tank&differs=1&date_from=2026-01-01");

    expect(lastParams()).toMatchObject({
      layer: ["author", "ow"],
      authorUserId: [5, 8],
      role: ["tank"],
      differsFromCanon: true,
      dateFrom: "2026-01-01"
    });
  });
});
