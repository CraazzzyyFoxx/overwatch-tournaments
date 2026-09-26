// @vitest-environment happy-dom
//
// The audit feed after P5-4. What is pinned here:
//  1. the `audit.read` gate — the screen refuses instead of asking the server
//     for a 403 per page;
//  2. a chip lands in the URL with EXACTLY ONE navigation. This screen used to
//     have two writers of the query string (its own `history.replaceState` and
//     the table's), and a filter change and a page change overwrote each other
//     depending on which landed last;
//  3. the same URL restores the chip, so a filtered feed is linkable;
//  4. "only this record" is one write for two params, not two writes;
//  5. a row opens the inspector with the field diff, not a dialog;
//  6. six columns do not fit a phone, so rows render as cards below `md`.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AuditLogRead } from "@/types/admin.types";
import AdminAuditPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const listAudit = vi.fn();

let permitted = true;
let superuser = false;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  // Pinned formatting: the assertions are about which row is on screen, not
  // about the locale, and the real formatter needs an intl provider.
}));
vi.mock("@/lib/datetime/client", () => ({
  useFormatter: () => ({
    dateTime: (value: Date) => value.toISOString().slice(0, 16).replace("T", " ")
  })
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: () => permitted,
    isLoaded: true,
    isSuperuser: superuser
  })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/services/admin.service", () => ({
  default: { listAudit: (...args: unknown[]) => listAudit(...args) }
}));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});
const push = vi.fn();

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/audit",
  useRouter: () => ({ replace, push }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

function entry(overrides: Partial<AuditLogRead> = {}): AuditLogRead {
  return {
    id: 4210,
    created_at: "2026-08-30T11:20:00Z",
    workspace_id: 1,
    actor_auth_user_id: 12,
    actor_label: "Nova",
    source: "admin",
    action: "tournament.update",
    entity_type: "tournament",
    entity_id: 14,
    entity_label: "MoonRise Mix Vol.4",
    before_json: { name: "MoonRise Mix Vol.3" },
    after_json: { name: "MoonRise Mix Vol.4" },
    reason: null,
    ip_address: "10.0.0.4",
    user_agent: null,
    correlation_id: null,
    ...overrides
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
  // Assigned in an effect, not during render: `next/navigation` is mocked, so
  // this is the only thing that re-reads the URL after a `replace`.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <>{render()}</>;
}

async function mount(search = "") {
  window.history.replaceState(null, "", `/admin/audit${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness render={() => <AdminAuditPage />} />
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

async function waitFor<T>(read: () => T | null | undefined | false, what: string): Promise<T> {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const value = read();
    if (value) return value as T;
    await settle(1, 25);
  }
  throw new Error(`timed out waiting for ${what}`);
}

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

function linkButton(text: string) {
  return Array.from(document.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

/**
 * The feed request, never the journal-start probe: the unfiltered screen fires
 * both, and the probe lands second because it only asks for the oldest row.
 * `entity_type` is the tell — the feed always sends it, the probe never does.
 */
function feedQuery(): Record<string, unknown> {
  return (
    listAudit.mock.calls
      .map((call) => (call[0] ?? {}) as Record<string, unknown>)
      .filter((args) => "entity_type" in args)
      .at(-1) ?? {}
  );
}

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  window.matchMedia = ((query: string) => ({
    // Both breakpoints the screen reads answer from the same width: the table
    // becomes cards below `md`, the inspector becomes a sheet below `lg`.
    matches: query.includes("max-width") ? width < 768 : width >= 1024,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
}

beforeEach(() => {
  permitted = true;
  superuser = false;
  replace.mockClear();
  push.mockClear();
  setViewportWidth(1280);
  listAudit
    .mockReset()
    .mockResolvedValue({ results: [entry()], total: 1, page: 1, per_page: 25 });
  document.body.innerHTML = "";
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
  document.body.innerHTML = "";
});

describe("/admin/audit", () => {
  it("refuses the feed without audit.read in the scope it would query", async () => {
    permitted = false;
    const container = await mount();

    expect(container.textContent).toContain("Unauthorized");
    // Not even the journal-start probe: every request here would be a 403.
    expect(listAudit).not.toHaveBeenCalled();
  });

  it("writes a chip to the URL with exactly one navigation", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Tournament updated"), "the audit row");
    expect(feedQuery().entity_type).toBeNull();
    replace.mockClear();

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(await waitFor(() => commandItem("Entity"), "the Entity filter"));
    await click(await waitFor(() => commandItem("Tournament"), "the Tournament option"));

    expect(new URLSearchParams(window.location.search).get("entity_type")).toBe("tournament");
    // The whole point of the rewrite: one writer, one history entry. Two would
    // race, and the loser's param would silently vanish from the request.
    expect(replace).toHaveBeenCalledTimes(1);
    expect(push).not.toHaveBeenCalled();
    await waitFor(() => feedQuery().entity_type === "tournament", "the narrowed request");
  });

  it("restores the chip from the URL the trail links to", async () => {
    await mount("?entity_type=tournament&entity_id=14");

    await waitFor(
      () => feedQuery().entity_type === "tournament" && feedQuery().entity_id === 14,
      "the entity-scoped request"
    );
    expect(
      document.querySelector('button[aria-label="Remove filter Entity: Tournament"]')
    ).not.toBeNull();
    expect(
      document.querySelector('button[aria-label="Remove filter Record: #14"]')
    ).not.toBeNull();
  });

  it("narrows to one record in a single write, both params together", async () => {
    const container = await mount();
    await waitFor(() => container.textContent?.includes("Tournament updated"), "the audit row");
    replace.mockClear();

    await click(linkButton("only this record"));

    const params = new URLSearchParams(window.location.search);
    expect(params.get("entity_type")).toBe("tournament");
    expect(params.get("entity_id")).toBe("14");
    expect(replace).toHaveBeenCalledTimes(1);
  });

  it("opens the inspector on a row instead of a dialog", async () => {
    const container = await mount();
    const row = await waitFor(
      () => container.querySelector("tbody tr[tabindex]"),
      "the first data row"
    );

    await click(row);

    expect(new URLSearchParams(window.location.search).get("id")).toBe("4210");
    const inspector = await waitFor(
      () => document.querySelector('aside[aria-label="Row inspector"]'),
      "the inspector"
    );
    expect(inspector.textContent).toContain("Tournament updated");
    // `AuditFieldDiff`, not a summary: the changed field and both sides of it.
    expect(inspector.textContent).toContain("name");
    expect(inspector.textContent).toContain("MoonRise Mix Vol.3");
    expect(inspector.textContent).toContain("10.0.0.4");
    expect(inspector.textContent).toContain("#4210");
  });

  it("renders rows as cards below md, where six columns do not fit", async () => {
    setViewportWidth(375);
    const container = await mount();
    const cards = await waitFor(() => {
      const list = container.querySelectorAll("ul[aria-label='Rows'] > li");
      return list.length > 0 ? list : null;
    }, "the mobile cards");

    expect(container.querySelector("table")).toBeNull();
    expect(cards[0].textContent).toContain("Tournament updated");
    // The card is chosen, not the first three columns: who and what, then when.
    expect(cards[0].textContent).toContain("Nova");
    expect(cards[0].textContent).toContain("MoonRise Mix Vol.4");
  });
});
