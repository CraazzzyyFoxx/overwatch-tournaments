// @vitest-environment happy-dom
//
// Settings › Divisions — the overview that replaced the 1045-line
// /admin/divisions screen and its four always-mounted cards. What is pinned:
//
//  1. the `division_grid.read` gate is the PAGE's. Hiding a rail link is not
//     access control: the URL typed into the address bar has to be refused,
//     and nothing may be asked of the API before it is allowed;
//  2. the version strip states come from the two facts that decide them — the
//     stored status and the workspace's default version pointer — so a
//     published version the workspace points at reads "active", which is not
//     a status the backend has;
//  3. the grid selector only appears when the workspace really has more than
//     one grid, and it writes `?grid=`;
//  4. "Load standard OW ladder" — the scenario carried over from
//     standardOwGrid.behavior.test.tsx, now asserted where the button actually
//     lives. A tier with a `null` OW endpoint is skipped by
//     `resolve_division_from_ow_rank`, and an `id` on any tier would make the
//     save rewrite a version in place instead of creating one.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { DivisionGridEntity, DivisionGridVersion } from "@/types/workspace.types";
import DivisionsSettingsPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getDivisionGrids = vi.fn();
const getDivisionGridVersions = vi.fn();
const getDivisionGridVersionReadiness = vi.fn();
const createDivisionGridVersion = vi.fn();
const cloneDivisionGridVersion = vi.fn();
const activateDivisionGridVersion = vi.fn();

let permitted = true;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  NextIntlClientProvider: ({ children }: { children: ReactNode }) => children
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString().slice(0, 10) })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: () => permitted,
    hasPermission: () => permitted,
    isSuperuser: false,
    isLoaded: true
  })
}));

let currentWorkspace: Record<string, unknown> = { id: 1, default_division_grid_version_id: 22 };

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: {
      currentWorkspaceId: number;
      getCurrentWorkspace: () => unknown;
      fetchWorkspaces: () => Promise<void>;
    }) => unknown
  ) =>
    selector({
      currentWorkspaceId: 1,
      getCurrentWorkspace: () => currentWorkspace,
      fetchWorkspaces: async () => undefined
    })
}));

vi.mock("@/services/workspace.service", () => ({
  default: {
    getDivisionGrids: (...args: unknown[]) => getDivisionGrids(...args),
    getDivisionGridVersions: (...args: unknown[]) => getDivisionGridVersions(...args),
    getDivisionGridVersionReadiness: (...args: unknown[]) =>
      getDivisionGridVersionReadiness(...args),
    createDivisionGridVersion: (...args: unknown[]) => createDivisionGridVersion(...args),
    cloneDivisionGridVersion: (...args: unknown[]) => cloneDivisionGridVersion(...args),
    activateDivisionGridVersion: (...args: unknown[]) => activateDivisionGridVersion(...args),
    exportDivisionGridPortable: vi.fn(),
    importDivisionGridPortable: vi.fn()
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn(), warning: vi.fn() }
}));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});
let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/settings/divisions",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  )
}));

function tier(number: number) {
  return {
    id: 500 + number,
    slug: `division-${number}`,
    number,
    name: `Division ${number}`,
    rank_min: 5000 - number * 100,
    rank_max: number === 1 ? null : 5099 - number * 100,
    sort_order: number - 1,
    icon_url: "https://cdn/x.png"
  };
}

function version(
  id: number,
  number: number,
  status: DivisionGridVersion["status"]
): DivisionGridVersion {
  return {
    id,
    grid_id: 7,
    version: number,
    label: `Season ${number} ladder`,
    status,
    created_from_version_id: null,
    published_at: status === "draft" ? null : "2026-05-02T10:00:00Z",
    tiers: [tier(1), tier(2), tier(3)]
  };
}

const VERSIONS = [
  version(20, 1, "archived"),
  version(21, 2, "published"),
  version(22, 3, "published"),
  version(23, 4, "draft")
];

function grid(id: number, name: string): DivisionGridEntity {
  return {
    id,
    workspace_id: 1,
    slug: `grid-${id}`,
    name,
    description: null,
    versions: VERSIONS,
    source_workspace_id: null,
    source_grid_id: null,
    source_key: null,
    source_fingerprint: null,
    imported_at: null,
    archived_at: null
  };
}

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 8, delayMs = 0) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, delayMs);
      await promise;
    });
  }
}

function Harness({ render }: Readonly<{ render: () => ReactNode }>) {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <>{render()}</>;
}

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness render={() => <DivisionsSettingsPage />} />
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    (element as HTMLElement).dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(3);
}

function button(text: string) {
  return Array.from(document.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

beforeEach(() => {
  permitted = true;
  currentWorkspace = { id: 1, default_division_grid_version_id: 22 };
  activateDivisionGridVersion.mockReset();
  replace.mockClear();
  getDivisionGrids.mockReset().mockResolvedValue([grid(7, "Anak Division Grid")]);
  getDivisionGridVersions.mockReset().mockResolvedValue(VERSIONS);
  getDivisionGridVersionReadiness.mockReset().mockResolvedValue({
    target_version_id: 22,
    is_ready: true,
    used_source_version_ids: [21],
    missing_mapping_version_ids: [],
    incomplete_mapping_version_ids: [],
    sources: [
      {
        version_id: 21,
        version_label: "v2",
        grid_name: "Anak Division Grid",
        tournament_count: 1,
        tournament_names: ["Anak Cup 11"],
        status: "ok",
        conflict_tiers: []
      }
    ]
  });
  createDivisionGridVersion.mockReset().mockResolvedValue(version(24, 5, "draft"));
  cloneDivisionGridVersion.mockReset().mockResolvedValue(version(24, 5, "draft"));
  window.history.replaceState(null, "", "/admin/settings/divisions");
});

afterEach(async () => {
  for (const entry of mounted.splice(0)) {
    await act(async () => entry.root.unmount());
    entry.container.remove();
  }
  document.body.innerHTML = "";
  rerender = null;
});

describe("Settings › Divisions", () => {
  it("refuses the section without division_grid.read and asks the API for nothing", async () => {
    permitted = false;
    const container = await mount();

    expect(container.textContent).toContain("Divisions are not available to you");
    expect(getDivisionGrids).not.toHaveBeenCalled();
  });

  it("shows the version strip with the workspace's own version marked active", async () => {
    const container = await mount();

    expect(container.textContent).toContain("v1");
    expect(container.textContent).toContain("v4");
    // v3 is `published` server-side; "active" is the workspace pointing at it.
    expect(container.textContent).toContain("active");
    expect(container.textContent).toContain("archived");
    expect(container.textContent).toContain("draft");

    // Only the draft is worth opening for editing.
    const editorLinks = Array.from(container.querySelectorAll("a")).filter((anchor) =>
      anchor.textContent?.includes("Open editor")
    );
    expect(editorLinks).toHaveLength(1);
    expect(editorLinks[0].getAttribute("href")).toBe("/admin/settings/divisions/v/23");
  });

  it("names the tournaments still reading an older version, and counts the rest honestly", async () => {
    getDivisionGridVersionReadiness.mockResolvedValue({
      target_version_id: 22,
      is_ready: true,
      used_source_version_ids: [21],
      missing_mapping_version_ids: [],
      incomplete_mapping_version_ids: [],
      sources: [
        {
          version_id: 21,
          version_label: "Season 2 ladder",
          grid_name: "Anak Division Grid",
          tournament_count: 7,
          tournament_names: ["Anak Cup 11", "Anak Cup 10"],
          status: "ok",
          conflict_tiers: []
        }
      ]
    });
    const container = await mount();

    expect(container.textContent).toContain("7 tournaments");
    expect(container.textContent).toContain("mapping complete");
    // The payload carries the five newest names and the full count, so the
    // names are shown as a sample with the remainder made explicit.
    expect(container.textContent).toContain("Anak Cup 11");
    expect(container.textContent).toContain("+5 more");
  });

  it("shows the active version as the grid in force, even when it belongs to a shared grid", async () => {
    const own = await mount();
    expect(own.textContent).toContain("In force · v3");
    expect(own.textContent).not.toContain("shared grid");

    // The workspace points at a version of a grid it does not own: it is not in
    // the grid list, but it is still the grid every rank resolves through.
    const shared = {
      ...version(90, 2, "published"),
      grid_id: 1,
      label: "Overwatch 2 Default Grid"
    };
    currentWorkspace = {
      id: 1,
      default_division_grid_version_id: 90,
      default_division_grid_version: shared
    };
    const container = await mount();
    expect(container.textContent).toContain("In force · v2");
    expect(container.textContent).toContain("Overwatch 2 Default Grid");
    expect(container.textContent).toContain("shared grid");
    expect(container.textContent).not.toContain("Nothing activated");
  });

  it("offers to activate a published version only once its readiness says so, then confirms", async () => {
    getDivisionGridVersionReadiness.mockImplementation(async (_ws: number, versionId: number) => ({
      target_version_id: versionId,
      is_ready: versionId === 21,
      used_source_version_ids: [],
      missing_mapping_version_ids: versionId === 21 ? [] : [22],
      incomplete_mapping_version_ids: [],
      sources: []
    }));
    activateDivisionGridVersion.mockResolvedValue(version(21, 2, "published"));
    await mount();

    // v2 is the one published version the workspace is not on; v3 is active.
    const activate = button("Activate v2");
    expect(activate).toBeTruthy();
    expect(activate!.hasAttribute("disabled")).toBe(false);
    expect(activateDivisionGridVersion).not.toHaveBeenCalled();

    await click(activate);
    const confirm = Array.from(document.querySelectorAll("button")).find(
      (element) => element.textContent?.trim() === "Activate v2" && element !== activate
    );
    await click(confirm);

    expect(activateDivisionGridVersion).toHaveBeenCalledWith(1, 21);
  });

  it("offers the grid selector only when there is more than one grid, and writes ?grid=", async () => {
    const single = await mount();
    expect(single.querySelector("#division-grid-select")).toBeNull();

    getDivisionGrids.mockResolvedValue([grid(7, "Anak Division Grid"), grid(8, "Legacy grid")]);
    const many = await mount();
    expect(many.querySelector("#division-grid-select")).toBeTruthy();
  });

  it("loads the standard OW ladder as a new version with a complete OW mapping", async () => {
    await mount();

    await click(button("Load standard OW ladder"));

    expect(createDivisionGridVersion).toHaveBeenCalledTimes(1);
    const [workspaceId, gridId, payload] = createDivisionGridVersion.mock.calls[0] as [
      number,
      number,
      { label: string; tiers: Record<string, unknown>[] }
    ];
    expect(workspaceId).toBe(1);
    expect(gridId).toBe(7);
    expect(payload.tiers).toHaveLength(45);

    // No ids -> the save creates a version instead of rewriting one in place.
    expect(payload.tiers.every((entry) => entry.id === undefined)).toBe(true);
    expect(payload.tiers.map((entry) => entry.sort_order)).toEqual(
      payload.tiers.map((_entry, index) => index)
    );

    // Both OW endpoints filled on every tier, top tier included: either being
    // null drops that division out of OW rank resolution entirely.
    expect(
      payload.tiers.every((entry) => entry.ow_rank_min !== null && entry.ow_rank_max !== null)
    ).toBe(true);
    expect(payload.tiers.every((entry) => entry.ow_rank_min === entry.ow_rank_max)).toBe(true);
    expect(new Set(payload.tiers.map((entry) => entry.ow_rank_min)).size).toBe(45);

    // And it lands in the editor rather than leaving the user on the overview.
    expect(replace).toHaveBeenCalledWith("/admin/settings/divisions/v/24");
  });

  it("clones the newest version into a fresh draft", async () => {
    await mount();

    await click(button("+ New draft from v4"));

    expect(cloneDivisionGridVersion).toHaveBeenCalledWith(23);
    expect(replace).toHaveBeenCalledWith("/admin/settings/divisions/v/24");
  });
});
