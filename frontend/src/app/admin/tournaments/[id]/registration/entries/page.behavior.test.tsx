// @vitest-environment happy-dom
//
// Registration › Entries (F4). What is pinned here:
//  1. the sections are one sub-tab bar, and the active one carries
//     `aria-current="page"` — they used to be reachable only from a dropdown
//     buried in the table's toolbar;
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

import { AuditTrailProvider } from "@/components/admin/AuditTrailSheet";
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
let teamFormation = "balancer";

const replace = vi.fn((url: string) => {
  const parsed = new URL(url, "http://localhost");
  window.history.replaceState(null, "", url);
  currentSearch = parsed.search;
  currentPath = parsed.pathname;
  rerender?.();
});

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "80" }),
  usePathname: () => currentPath,
  useSearchParams: () => new URLSearchParams(currentSearch),
  useRouter: () => ({ replace, push: replace })
}));

vi.mock("next/link", () => ({
  default: forwardRef<
    HTMLAnchorElement,
    { href: string; children: ReactNode } & React.AnchorHTMLAttributes<HTMLAnchorElement>
  >(function Link({ href, children, ...props }, ref) {
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

vi.mock("@/services/admin.service", () => ({
  default: {
    getTournament: vi.fn(async () => ({
      id: 80,
      workspace_id: 1,
      name: "Anak Cup",
      team_formation: teamFormation
    }))
  }
}));
vi.mock("@/services/balancer-admin.service", () => ({
  default: {
    listRegistrations: (...args: unknown[]) => listRegistrations(...args),
    getRegistrationForm: vi.fn().mockResolvedValue({ require_open_profile: false }),
    listStatusCatalog: vi.fn().mockResolvedValue([]),
    exportRegistrationsToUsers: vi.fn(),
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
  default: { getForm: vi.fn().mockResolvedValue(null) }
}));
// The inspector's rank chart fetches on mount; this suite is about the screen,
// not the chart, and a live fetch outlives the test's window teardown.
vi.mock("@/components/RankHistory", () => ({
  default: () => <p>Rank history</p>
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
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
    tournament_id: 80,
    workspace_id: 1,
    user_id: id,
    display_name: `Player ${id}`,
    battle_tag: `Player${id}#1234`,
    smurf_tags_json: [],
    discord_nick: null,
    twitch_nick: null,
    stream_pov: false,
    roles: [],
    notes: null,
    admin_notes: null,
    custom_fields_json: null,
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
  window.history.replaceState(null, "", `${currentPath}${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push(root);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={{}}>
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

beforeEach(() => {
  canTeamRead = true;
  teamFormation = "balancer";
  rerender = null;
  replace.mockClear();
  listRegistrations.mockReset().mockResolvedValue(POOL);
  // The inspector is a side panel above `lg` and a sheet below it.
  window.matchMedia = ((query: string) => ({
    matches: true,
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
  it("gives the sections one sub-tab bar and marks the active one", async () => {
    const scope = await mount();
    const nav = scope.querySelector("nav[aria-label='Registration sections']");
    const links = [...(nav?.querySelectorAll("a") ?? [])];

    // No `teams`: this tournament balances, so registered teams do not exist.
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/admin/tournaments/80/registration/entries",
      "/admin/tournaments/80/registration/form",
      "/admin/tournaments/80/registration/feed",
      "/admin/tournaments/80/registration/rank-autofill"
    ]);
    expect(
      links.filter((link) => link.getAttribute("aria-current") === "page").map((l) => l.textContent)
    ).toEqual(["Entries"]);
  });

  it("offers the teams section only when captains form the teams", async () => {
    teamFormation = "registration";

    const scope = await mount();
    const links = [
      ...(scope.querySelector("nav[aria-label='Registration sections']")?.querySelectorAll("a") ??
        [])
    ];

    // A linkable section beside its siblings, not a Radix `Tabs` pair inside
    // the entries table whose state no URL could carry.
    expect(links.map((link) => link.getAttribute("href"))).toContain(
      "/admin/tournaments/80/registration/teams"
    );
    expect(links.map((link) => link.textContent)).toEqual([
      "Entries",
      "Teams",
      "Form",
      "Sheets feed",
      "Rank autofill"
    ]);
  });

  it("hides the section body without team.read", async () => {
    canTeamRead = false;

    const scope = await mount("", false);

    expect(scope.querySelector("nav[aria-label='Registration sections']")).not.toBeNull();
    expect(scope.querySelector("table")).toBeNull();
    expect(listRegistrations).not.toHaveBeenCalled();
  });

  it("writes a picked chip into the URL", async () => {
    const scope = await mount();

    await click(scope.querySelector("button[aria-label='Add filter']"));
    await click(commandItem("Admission"));
    await click(commandItem("Admitted"));

    expect(new URL(replace.mock.calls.at(-1)![0], "http://x").searchParams.get("admission")).toBe(
      "admitted"
    );
  });

  it("restores the chip from the URL and narrows the rows", async () => {
    const scope = await mount("?admission=admitted");

    expect(scope.querySelector("button[aria-label='Remove filter Admission: Admitted']")).not.toBeNull();
    expect(scope.querySelectorAll("tbody tr").length).toBe(1);
  });

  it("drops the page cursor when the filters are cleared", async () => {
    const scope = await mount("?admission=admitted&page=3");

    await click(
      [...scope.querySelectorAll("button")].find(
        (button) => button.textContent?.trim() === "Clear all"
      )
    );

    const url = new URL(replace.mock.calls.at(-1)![0], "http://x");
    expect(url.searchParams.get("admission")).toBeNull();
    expect(url.searchParams.get("page")).toBeNull();
  });

  it("opens a row in the inspector through ?id=", async () => {
    const scope = await mount();

    await click(scope.querySelector("tbody tr"));

    expect(new URL(replace.mock.calls.at(-1)![0], "http://x").searchParams.get("id")).toBe("1");

    const withInspector = await mount("?id=1");
    const inspector = withInspector.querySelector("aside[aria-label='Row inspector']");
    expect(inspector?.textContent).toContain("Player1#1234");
    expect(inspector?.textContent).toContain("Admission");
  });
});
