// @vitest-environment happy-dom
//
// The draft editor route. What is pinned:
//
//  1. the `division_grid.read` gate is the page's, and `division_grid.update`
//     decides editable-vs-read-only — a draft is not writable just because it
//     is a draft;
//  2. Publish is refused while any older version a tournament still reads has
//     an incomplete mapping. This is the whole point of splitting Publish from
//     Activate: an immutable version that no old tournament can be translated
//     into would strand those tournaments' players;
//  3. `?tab=` selects the centre view, so a link into Mappings (which is where
//     the importer sends the user) lands there;
//  4. cutting the ladder is what edits the draft: a click on a rank splits the
//     band and the save bar appears with the draft's summary;
//  5. a published version opens read-only, offering a clone instead of edits.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  DivisionGridActivationReadiness,
  DivisionGridVersion,
  DivisionTier
} from "@/types/workspace.types";
import DivisionDraftEditorPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getDivisionGridVersion = vi.fn();
const getDivisionGridVersionReadiness = vi.fn();
const getDivisionGridMapping = vi.fn();
const updateDivisionGridVersion = vi.fn();
const publishDivisionGridVersion = vi.fn();
const putDivisionGridMapping = vi.fn();

let canRead = true;
let canUpdate = true;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  NextIntlClientProvider: ({ children }: { children: ReactNode }) => children
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) =>
      permission === "division_grid.update" ? canUpdate : canRead,
    hasPermission: () => canRead,
    isSuperuser: false,
    isLoaded: true
  })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: {
      currentWorkspaceId: number;
      getCurrentWorkspace: () => unknown;
    }) => unknown
  ) =>
    selector({
      currentWorkspaceId: 1,
      getCurrentWorkspace: () => ({ id: 1, default_division_grid_version_id: 22 })
    })
}));

vi.mock("@/services/workspace.service", () => ({
  default: {
    getDivisionGridVersion: (...args: unknown[]) => getDivisionGridVersion(...args),
    getDivisionGridVersionReadiness: (...args: unknown[]) =>
      getDivisionGridVersionReadiness(...args),
    getDivisionGridMapping: (...args: unknown[]) => getDivisionGridMapping(...args),
    updateDivisionGridVersion: (...args: unknown[]) => updateDivisionGridVersion(...args),
    publishDivisionGridVersion: (...args: unknown[]) => publishDivisionGridVersion(...args),
    putDivisionGridMapping: (...args: unknown[]) => putDivisionGridMapping(...args),
    activateDivisionGridVersion: vi.fn(),
    deleteDivisionGridVersion: vi.fn(),
    cloneDivisionGridVersion: vi.fn(),
    uploadDivisionIcon: vi.fn()
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
  useParams: () => ({ versionId: "23" }),
  usePathname: () => "/admin/settings/divisions/v/23",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  )
}));

// The image loader needs Next's config; the crest is decorative here.
vi.mock("next/image", () => ({
  default: ({ alt }: { alt: string }) => <span data-crest={alt} />
}));

function tier(
  id: number,
  number: number,
  name: string,
  rankMin: number,
  rankMax: number | null
): DivisionTier {
  return {
    id,
    slug: name.toLowerCase(),
    number,
    name,
    rank_min: rankMin,
    rank_max: rankMax,
    sort_order: number - 1,
    icon_url: "https://cdn/x.png"
  };
}

/** Three bands partitioning the ladder: Champion 1–3, Champion 4–Grandmaster 5, the rest. */
const DRAFT_TIERS = [
  tier(501, 1, "Champion", 4700, null),
  tier(502, 2, "Elite", 4000, 4699),
  tier(503, 3, "Open", 0, 3999)
];

function version(
  id: number,
  number: number,
  status: DivisionGridVersion["status"],
  tiers = DRAFT_TIERS
): DivisionGridVersion {
  return {
    id,
    grid_id: 7,
    version: number,
    label: `Season ${number} ladder`,
    status,
    created_from_version_id: id === 23 ? 22 : null,
    published_at: status === "draft" ? null : "2026-05-02T10:00:00Z",
    tiers
  };
}

function readiness(
  overrides: Partial<DivisionGridActivationReadiness> = {}
): DivisionGridActivationReadiness {
  return {
    target_version_id: 23,
    is_ready: true,
    used_source_version_ids: [21],
    missing_mapping_version_ids: [],
    incomplete_mapping_version_ids: [],
    sources: [
      {
        version_id: 21,
        version_label: "v2",
        grid_name: "Anak Division Grid",
        tournament_count: 2,
        tournament_names: [],
        status: "ok",
        conflict_tiers: []
      }
    ],
    ...overrides
  };
}

const mounted: { root: Root; container: HTMLElement }[] = [];

/**
 * The `xl` rail vs the "Impact" sub-tab (F12 ·8).
 *
 * `min-width` queries answer for the editor's own rail breakpoint; the
 * `max-width` one `DataTable` asks about is the mobile-card switch and
 * stays off, so the table keeps rendering rows either way.
 */
function mockViewport(wide: boolean) {
  window.matchMedia = ((query: string) => ({
    matches: query.includes("min-width") ? wide : false,
    media: query,
    onchange: null,
    addListener: () => undefined,
    removeListener: () => undefined,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
}

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
        <Harness render={() => <DivisionDraftEditorPage />} />
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

function byLabel(label: string) {
  return document.querySelector(`[aria-label="${label}"]`);
}

beforeEach(() => {
  canRead = true;
  canUpdate = true;
  mockViewport(true);
  replace.mockClear();
  getDivisionGridVersion.mockReset().mockImplementation(async (id: number) => {
    if (id === 23) return version(23, 4, "draft");
    if (id === 22) return version(22, 3, "published");
    return version(21, 2, "published", [tier(401, 1, "Old top", 4000, null), tier(402, 2, "Old rest", 0, 3999)]);
  });
  getDivisionGridVersionReadiness.mockReset().mockResolvedValue(readiness());
  getDivisionGridMapping.mockReset().mockResolvedValue({
    id: 1,
    source_version_id: 21,
    target_version_id: 23,
    name: "v2 → v4",
    is_complete: true,
    rules: [
      { source_tier_id: 401, target_tier_id: 501, weight: 1, is_primary: true },
      { source_tier_id: 402, target_tier_id: 503, weight: 1, is_primary: true }
    ]
  });
  updateDivisionGridVersion.mockReset().mockResolvedValue(version(23, 4, "draft"));
  publishDivisionGridVersion.mockReset().mockResolvedValue(version(23, 4, "published"));
  putDivisionGridMapping.mockReset().mockResolvedValue({ is_complete: true, rules: [] });
  window.history.replaceState(null, "", "/admin/settings/divisions/v/23");
});

afterEach(async () => {
  for (const entry of mounted.splice(0)) {
    await act(async () => entry.root.unmount());
    entry.container.remove();
  }
  document.body.innerHTML = "";
  rerender = null;
});

describe("Divisions › draft editor", () => {
  it("refuses the route without division_grid.read and loads nothing", async () => {
    canRead = false;
    const container = await mount();

    expect(container.textContent).toContain("This draft is not available to you");
    expect(getDivisionGridVersion).not.toHaveBeenCalled();
  });

  it("opens a draft the caller may not update as read-only", async () => {
    canUpdate = false;
    const container = await mount();

    expect(container.textContent).toContain("division_grid.update");
    expect(button("Undo last change")).toBeUndefined();
    expect(byLabel("Start a new division at Champion 2")).toBeNull();
  });

  it("refuses Publish while an older version's mapping is incomplete", async () => {
    getDivisionGridVersionReadiness.mockResolvedValue(
      readiness({ is_ready: false, incomplete_mapping_version_ids: [21] })
    );
    const container = await mount();

    const publish = button("Publish v4");
    expect(publish).toBeTruthy();
    expect(publish!.disabled).toBe(true);
    expect(container.textContent).toContain("1 mapping decision left in the Mappings tab");
  });

  it("allows Publish once every mapping is complete and the draft is saved", async () => {
    const container = await mount();

    expect(button("Publish v4")!.disabled).toBe(false);
    expect(container.textContent).toContain("Every older version maps onto this one");
    expect(container.textContent).toContain("belongs to exactly one division");
  });

  it("selects the centre view from ?tab=", async () => {
    window.history.replaceState(null, "", "/admin/settings/divisions/v/23?tab=mappings");
    const container = await mount();

    expect(container.textContent).toContain("v2 \u2192 v4");
    expect(container.textContent).toContain("source divisions");

    window.history.replaceState(null, "", "/admin/settings/divisions/v/23?tab=changes");
    const changes = await mount();
    expect(changes.textContent).toContain("identical to v3");
  });

  it("cuts the ladder and surfaces the draft summary in the save bar", async () => {
    const container = await mount();
    expect(container.querySelector('[aria-label="unsavedChanges"]')).toBeNull();

    await click(byLabel("Start a new division at Champion 2"));

    const bar = container.querySelector('[aria-label="unsavedChanges"]');
    expect(bar).toBeTruthy();
    expect(bar!.textContent).toContain("4 divisions");
    expect(bar!.textContent).toContain("1 edit");
    // The new band has no tier id yet, so mappings cannot be computed onto it.
    expect(container.textContent).toContain("The draft is saved as a version");

    // Undo puts it back and takes the bar away with it.
    await click(button("Undo last change"));
    expect(container.querySelector('[aria-label="unsavedChanges"]')).toBeNull();
  });

  it("saves the bands as tiers and the mappings alongside them", async () => {
    const container = await mount();
    await click(byLabel("Start a new division at Champion 2"));
    await click(button("Save draft"));

    expect(updateDivisionGridVersion).toHaveBeenCalledTimes(1);
    const [versionId, payload] = updateDivisionGridVersion.mock.calls[0] as [
      number,
      { tiers: Record<string, unknown>[] }
    ];
    expect(versionId).toBe(23);
    expect(payload.tiers).toHaveLength(4);
    // The upper half keeps the original tier id; the new band has none.
    expect(payload.tiers.map((entry) => entry.id)).toEqual([501, undefined, 502, 503]);
    expect(payload.tiers.every((entry) => entry.ow_rank_min !== null)).toBe(true);

    expect(putDivisionGridMapping).toHaveBeenCalledTimes(1);
    const [sourceId, targetId] = putDivisionGridMapping.mock.calls[0] as [number, number];
    expect(sourceId).toBe(21);
    expect(targetId).toBe(23);
    expect(container).toBeTruthy();
  });

  it("moves the impact rail into a fourth tab below xl, and nowhere above it", async () => {
    const wide = await mount();
    const wideTabs = Array.from(wide.querySelectorAll("nav a")).map((link) =>
      link.textContent?.trim()
    );
    expect(wideTabs).not.toContain("Impact");
    // Still on screen — it is the rail, which is why the tab is redundant.
    expect(wide.textContent).toContain("Impact of this draft");

    mockViewport(false);
    window.history.replaceState(null, "", "/admin/settings/divisions/v/23?tab=impact");
    const narrow = await mount();
    const narrowTabs = Array.from(narrow.querySelectorAll("nav a")).map((link) =>
      link.textContent?.trim()
    );
    expect(narrowTabs).toContain("Impact");
    expect(narrow.textContent).toContain("Ready to publish?");
  });
});
