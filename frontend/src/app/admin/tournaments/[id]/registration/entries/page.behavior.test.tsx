// @vitest-environment happy-dom
//
// Registration › Entries (F4). What is pinned here:
//  1. the sub-tab bar holds the views of who entered (entries, teams) and the
//     tools that act on entries (Sheets feed, rank autofill), each a routed
//     tab;
//  2. `teams` is offered only on a tournament that forms its teams by
//     registration — it used to be a Radix `Tabs` switcher inside this page,
//     which is neither the admin's one tab implementation nor linkable;
//  3. the tab's `team.read` gate hides the body, not just the link;
//  4. a chip writes the URL and a reload restores it — filter state that lives
//     in component state cannot be linked, which is why chips replaced the
//     header funnels;
//  5. clicking a row opens the inspector through `?id=`, not a dialog.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, forwardRef, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditTrailProvider } from "@/components/kit/AuditTrailSheet";
import en from "@/i18n/messages/en.json";
import type { AdminRegistration } from "@/types/balancer-admin.types";
import RegistrationLayout from "../layout";
import RegistrationEntriesPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let currentSearch = "";
let currentPath = "/admin/tournaments/80/registration/entries";
let rerender: (() => void) | null = null;
let canTeamRead = true;
let intake: "solo" | "team" = "solo";

// Every URL write re-renders from the new `useSearchParams` in the app — the
// router's `replace` and, through Next's History patch, the inspector's native
// `replaceState`. Both land here as "write `window.history`, poke the harness".
const replace = vi.fn((url: string) => window.history.replaceState(null, "", url));
const nativeReplaceState = window.history.replaceState.bind(window.history);
window.history.replaceState = (data, unused, url) => {
  const parsed = new URL(String(url), "http://localhost");
  nativeReplaceState(data, unused, url);
  currentSearch = parsed.search;
  currentPath = parsed.pathname;
  rerender?.();
};

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "80" }),
  usePathname: () => currentPath,
  useSearchParams: () => new URLSearchParams(currentSearch),
  useRouter: () => ({ replace, push: replace })
}));

vi.mock("next/link", () => ({
  default: forwardRef<
    HTMLAnchorElement,
    {
      href: string;
      children: ReactNode;
      prefetch?: boolean | null;
    } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function Link({ href, children, prefetch: _prefetch, ...props }, ref) {
    return (
      <a ref={ref} href={href} {...props}>
        {children}
      </a>
    );
  })
}));

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    isLoaded: true,
    canAccessPermission: (permission: string) =>
      permission === "team.read" ? canTeamRead : true
  })
}));

const listRegistrations = vi.fn();
const getPublicForm = vi.fn();

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: vi.fn(async () => ({
      id: 80,
      workspace_id: 1,
      name: "Anak Cup",
      flow_nodes: [
        { id: 7, kind: "registration", name: "Registration", status: "open", config: { intake }, schedule: [], stage_id: null }
      ]
    }))
  }
}));
vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    listRegistrations: (...args: unknown[]) => listRegistrations(...args),
    getRegistrationForm: vi.fn().mockResolvedValue({ require_open_profile: false }),
    listStatusCatalog: vi.fn().mockResolvedValue([]),
    createManualRegistration: vi.fn(),
    updateRegistration: vi.fn(),
    approveRegistration: vi.fn(),
    rejectRegistration: vi.fn(),
    withdrawRegistration: vi.fn(),
    restoreRegistration: vi.fn(),
    deleteRegistration: vi.fn(),
    bulkApproveRegistrations: vi.fn(),
    setBalancerStatus: vi.fn(),
    includeInBalancer: vi.fn(),
    checkInRegistration: vi.fn(),
    bulkAddToBalancer: vi.fn()
  }
}));
vi.mock("@/services/registration.service", () => ({
  default: { getForm: (...args: unknown[]) => getPublicForm(...args) }
}));
// The inspector's rank chart fetches on mount; this suite is about the screen,
// not the chart, and a live fetch outlives the test's window teardown.
vi.mock("@/components/RankHistory", () => ({
  default: () => <p>Rank history</p>
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: { currentWorkspaceId: number; getCurrentWorkspace: () => undefined }) => unknown
  ) => selector({ currentWorkspaceId: 1, getCurrentWorkspace: () => undefined })
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

function statusMeta(value: string, scope: "registration" | "balancer", excludes = false) {
  return {
    value,
    scope,
    is_builtin: true,
    kind: "builtin",
    is_override: false,
    can_edit: false,
    can_delete: false,
    can_reset: false,
    icon_slug: null,
    icon_color: null,
    name: value,
    description: null,
    excludes_from_balancer: excludes,
    excludes_from_ready: false
  };
}

function registration(
  id: number,
  decision: AdminRegistration["admission"]["decision"]
): AdminRegistration {
  return {
    id,
    entry_id: id + 1000,
    registration_node_id: 7,
    tournament_id: 80,
    workspace_id: 1,
    user_id: id,
    display_name: `Player ${id}`,
    primary_handle: `Player${id}#1234`,
    roles: [],
    answers: { identity_battlenet: [`Player${id}#1234`], stream_pov: false },
    form_version_id: 2,
    form_version_stale: false,
    admin_notes: null,
    status: "approved",
    status_meta: statusMeta("approved", "registration"),
    balancer_status: "ready",
    balancer_status_meta: statusMeta("ready", "balancer"),
    checked_in: false,
    profiles_open: true,
    admission: {
      decision,
      requirements: [],
      blockers: [],
      overridden: [],
      checked_in: false,
      ready: false
    },
    source: "manual",
    submitted_at: "2026-07-30T17:00:00Z",
    reviewed_at: null
  } as unknown as AdminRegistration;
}

const POOL = [registration(1, "admitted"), registration(2, "not_admitted")];

function tick(ms = 0) {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, ms);
  return promise;
}

const mounted: Root[] = [];

function Harness() {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return (
    <RegistrationLayout>
      <RegistrationEntriesPage />
    </RegistrationLayout>
  );
}

async function mount(search = "", expectTable = true) {
  currentSearch = search;
  currentPath = "/admin/tournaments/80/registration/entries";
  // A harness already mounted by this test re-renders from the new URL.
  await act(async () => {
    window.history.replaceState(null, "", `${currentPath}${search}`);
  });
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push(root);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <AuditTrailProvider>
            <Harness />
          </AuditTrailProvider>
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  // The page code-splits the table, so the first paint is the skeleton and the
  // module graph is still being transformed. Poll instead of guessing a tick
  // count, then flush a few more turns for React Query's commits.
  for (let turn = 0; turn < 100 && expectTable; turn += 1) {
    await act(async () => {
      await tick(5);
    });
    if (container.querySelector("tbody tr")) break;
  }
  for (let turn = 0; turn < 5; turn += 1) {
    await act(async () => {
      await tick();
    });
  }
  return container;
}

function click(node: Element | null | undefined) {
  if (!node) throw new Error("Expected a clickable node");
  return act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function commandItem(label: string) {
  return [...document.querySelectorAll('[cmdk-item=""]')].find((item) =>
    item.textContent?.trim().startsWith(label)
  );
}

/** Popovers and toolbars mount a few ticks late; under a loaded runner one tick is not enough. */
async function eventually<T>(find: () => T | null | undefined): Promise<T | undefined> {
  for (let turn = 0; turn < 50; turn += 1) {
    const found = find();
    if (found) return found;
    await act(async () => {
      await tick(5);
    });
  }
  return undefined;
}

function findCommandItem(label: string) {
  return eventually(() => commandItem(label));
}

beforeEach(() => {
  canTeamRead = true;
  intake = "solo";
  rerender = null;
  replace.mockClear();
  listRegistrations.mockReset().mockResolvedValue(POOL);
  getPublicForm.mockReset().mockResolvedValue(null);
  // The inspector is a side panel above `lg` and a sheet below it; the table is a table above `md`.
  window.matchMedia = ((query: string) => ({
    matches: !query.includes("max-width"),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
});

afterEach(async () => {
  await act(async () => {
    for (const root of mounted.splice(0)) root.unmount();
  });
  document.body.innerHTML = "";
  document.body.style.pointerEvents = "";
});

describe("Registration entries", () => {
  it("offers the tools as routed tabs beside entries", async () => {
    const scope = await mount();
    const links = [
      ...(scope.querySelector("nav[aria-label='Registration sections']")?.querySelectorAll("a") ??
        [])
    ];

    // No `teams`: this tournament balances, so the bar is entries and the tools.
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/admin/tournaments/80/registration/entries",
      "/admin/tournaments/80/registration/feed",
      "/admin/tournaments/80/registration/rank-autofill"
    ]);
  });

  it("offers the teams section only when captains form the teams", async () => {
    intake = "team";

    const scope = await mount();
    const links = [
      ...(scope.querySelector("nav[aria-label='Registration sections']")?.querySelectorAll("a") ??
        [])
    ];

    // A linkable section beside its sibling, not a Radix `Tabs` pair inside
    // the entries table whose state no URL could carry.
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/admin/tournaments/80/registration/entries",
      "/admin/tournaments/80/registration/teams",
      "/admin/tournaments/80/registration/feed",
      "/admin/tournaments/80/registration/rank-autofill"
    ]);
    expect(
      links.filter((link) => link.getAttribute("aria-current") === "page").map((l) => l.textContent)
    ).toEqual(["Entries"]);
  });

  it("hides the section body without team.read", async () => {
    canTeamRead = false;
    intake = "team";

    const scope = await mount("", false);

    expect(scope.querySelector("nav[aria-label='Registration sections']")).not.toBeNull();
    expect(scope.querySelector("table")).toBeNull();
    expect(listRegistrations).not.toHaveBeenCalled();
  });

  it("writes a picked chip into the URL", async () => {
    const scope = await mount();

    await click(await eventually(() => scope.querySelector("button[aria-label='Add filter']")));
    await click(await findCommandItem("Admission"));
    await click(await findCommandItem("Admitted"));

    expect(new URL(replace.mock.calls.at(-1)![0], "http://x").searchParams.get("admission")).toBe(
      "admitted"
    );
  });

  it("restores the chip from the URL and narrows the rows", async () => {
    const scope = await mount("?admission=admitted");

    expect(
      await eventually(() => scope.querySelector("button[aria-label='Remove filter Admission: Admitted']"))
    ).toBeDefined();
    expect(scope.querySelectorAll("tbody tr[data-row-id]").length).toBe(1);
  });

  it("drops the page cursor when the filters are cleared", async () => {
    // "Clear all" is offered only from two chips up.
    const scope = await mount("?admission=admitted&status=approved&page=3");

    await click(
      [...scope.querySelectorAll("button")].find(
        (button) => button.textContent?.trim() === "Clear all"
      )
    );

    const url = new URL(replace.mock.calls.at(-1)![0], "http://x");
    expect(url.searchParams.get("admission")).toBeNull();
    expect(url.searchParams.get("status")).toBeNull();
    expect(url.searchParams.get("page")).toBeNull();
  });

  it("opens a row in the inspector through ?id=", async () => {
    const scope = await mount();

    await click(scope.querySelector("tbody tr"));

    expect(new URLSearchParams(window.location.search).get("id")).toBe("1");

    const withInspector = await mount("?id=1");
    const inspector = withInspector.querySelector("aside[aria-label='Row inspector']");
    expect(inspector?.textContent).toContain("Player1#1234");
    expect(inspector?.textContent).toContain("Admission");
  });

  it("still reads an answer the form no longer asks, and says it is from an older version", async () => {
    // The whole point of versioned schemas: a registration filed against an
    // older version keeps answers this form has since dropped. The table has no
    // column for them — only the current schema builds columns — so the
    // inspector is where they have to remain readable.
    getPublicForm.mockResolvedValue({
      id: 9,
      tournament_id: 80,
      workspace_id: 1,
      form_schema: {
        schema_version: 1,
        sections: [
          {
            key: "details",
            fields: [
              {
                key: "vk",
                kind: "text",
                label: "VK profile",
                required: false,
                visibility: "public",
                params: {},
              }
            ]
          }
        ]
      },
      version_id: 4,
      version_number: 2
    });
    listRegistrations.mockResolvedValue([
      {
        ...registration(1, "admitted"),
        answers: { vk: "vk.com/player", why_this_tournament: "a question we dropped" },
        form_version_id: 3,
        form_version_stale: true
      }
    ]);

    const withInspector = await mount("?id=1");
    const inspector = withInspector.querySelector("aside[aria-label='Row inspector']");

    expect(inspector?.textContent).toContain("VK profile");
    expect(inspector?.textContent).toContain("vk.com/player");
    expect(inspector?.textContent).toContain("why_this_tournament");
    expect(inspector?.textContent).toContain("a question we dropped");
    expect(inspector?.textContent).toContain("no longer asked");
    expect(inspector?.textContent).toContain("older version of this form");
  });
});
