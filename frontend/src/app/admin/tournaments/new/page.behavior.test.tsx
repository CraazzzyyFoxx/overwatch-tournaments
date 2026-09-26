// @vitest-environment happy-dom
//
// The new-tournament wizard on the T6 `WizardShell` (F16). What is pinned here:
//  1. the route is gated on `tournament.create` — the list already hides the
//     entry point behind that permission, so the route it links to must agree;
//  2. the active step comes from `?step=`, so a reload keeps the place and the
//     rail marks exactly one step with `aria-current="step"` (WizardShell's
//     contract, not re-implemented here);
//  3. Continue writes the NEXT step to the URL rather than to local state;
//  4. Continue on step 1 with an empty form warns and does not advance —
//     validation runs on submit, so the button always stays reachable;
//  5. "Import from Challonge instead" is a link to `?source=challonge` that
//     keeps `step`: it is an alternative entry to this same wizard, not a step.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import NewTournamentPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let currentSearch = "";
let rerender: (() => void) | null = null;

const navigate = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  currentSearch = new URL(url, "http://localhost").search;
  rerender?.();
});

const permissions: Record<string, boolean> = {};
const warning = vi.fn();

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({ dateTime: () => "01 January 2026" })
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/tournaments/new",
  useRouter: () => ({ push: navigate, replace: navigate }),
  useSearchParams: () => new URLSearchParams(currentSearch)
}));
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) => permissions[permission] ?? true
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (
    selector: (state: { currentWorkspaceId: number; workspaces: unknown[] }) => unknown
  ) => selector({ currentWorkspaceId: 1, workspaces: [] })
}));
vi.mock("@/services/workspace.service", () => ({
  default: { getDivisionGrids: vi.fn().mockResolvedValue([]) }
}));
vi.mock("@/services/balancer-admin.service", () => ({
  default: { getSubscriptionRequirement: vi.fn().mockResolvedValue({ requirement: null }) }
}));
vi.mock("@/services/tournament.service", () => ({
  default: { getAll: vi.fn().mockResolvedValue({ results: [] }) }
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    createTournament: vi.fn(),
    createTournamentWithGroups: vi.fn(),
    updateTournament: vi.fn(),
    setTournamentSchedule: vi.fn()
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: {
    success: vi.fn(),
    warning: (...args: unknown[]) => warning(...args),
    apiError: vi.fn()
  }
}));

let container: HTMLElement;
let root: Root;

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

function Harness() {
  // `useSearchParams` is mocked from a module-level string, so a URL write has
  // to force the re-render a real router would have caused. Published from an
  // effect, not during render: assigning it inline is a render side effect.
  const [, force] = useState(0);
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <NewTournamentPage />;
}

async function render(search = "") {
  currentSearch = search;
  window.history.replaceState(null, "", `/admin/tournaments/new${search}`);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>
    );
  });
  for (let turn = 0; turn < 3; turn += 1) {
    await act(async () => {
      await tick();
    });
  }
}

async function click(element: Element | null | undefined) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function button(label: string) {
  return [...container.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === label
  );
}

function currentRailStep() {
  return container
    .querySelector('ol[aria-label="Steps"] [aria-current="step"]')
    ?.textContent?.trim();
}

function heading() {
  return container.querySelector("h2")?.textContent?.trim();
}

beforeEach(() => {
  navigate.mockClear();
  warning.mockClear();
  for (const key of Object.keys(permissions)) delete permissions[key];
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
});

describe("NewTournamentPage", () => {
  it("blocks the route without tournament.create", async () => {
    permissions["tournament.create"] = false;
    await render();

    expect(container.textContent).toContain("Unauthorized");
    expect(container.querySelector('ol[aria-label="Steps"]')).toBeNull();
    expect(button("Continue")).toBeUndefined();
  });

  it("reads the active step from the URL", async () => {
    await render("?step=rules");

    expect(currentRailStep()).toContain("Rules");
    expect(heading()).toBe("Rules");
    expect(container.querySelectorAll('ol[aria-label="Steps"] [aria-current="step"]')).toHaveLength(
      1
    );
  });

  it("falls back to step 1 for a missing or unknown step", async () => {
    await render("?step=nope");

    expect(currentRailStep()).toContain("Basics");
    expect(heading()).toBe("Basics");
  });

  it("hides the registration step without team.create", async () => {
    permissions["team.create"] = false;
    await render();

    const labels = [...container.querySelectorAll('ol[aria-label="Steps"] li')].map((node) =>
      node.textContent?.trim()
    );
    expect(labels.some((label) => label?.includes("Registration"))).toBe(false);
    expect(container.textContent).toContain("Step 1 of 4");
  });

  it("Continue writes the next step to the URL", async () => {
    await render("?step=schedule");

    await click(button("Continue"));

    expect(navigate).toHaveBeenCalledWith("/admin/tournaments/new?step=rules");
    expect(heading()).toBe("Rules");
    expect(currentRailStep()).toContain("Rules");
  });

  it("Continue on step 1 warns instead of advancing an empty form", async () => {
    await render();

    await click(button("Continue"));

    expect(warning).toHaveBeenCalledOnce();
    expect(navigate).not.toHaveBeenCalled();
    expect(heading()).toBe("Basics");
  });

  it("offers the Challonge import as a link that keeps the step", async () => {
    await render("?step=basics");

    const link = container.querySelector<HTMLAnchorElement>('a[href*="source=challonge"]');
    expect(link?.textContent).toContain("Import from Challonge instead");
    expect(link?.getAttribute("href")).toBe("/admin/tournaments/new?step=basics&source=challonge");
  });
});
