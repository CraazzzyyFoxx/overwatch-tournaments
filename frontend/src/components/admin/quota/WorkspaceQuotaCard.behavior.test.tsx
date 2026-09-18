// @vitest-environment happy-dom
//
// The three override scopes are one tab row now, and tabbing has two ways to
// go wrong that nothing else catches.
//
// A scope's form holds unsaved work. If switching tabs unmounted the panel, a
// half-typed override would vanish without a word — so every panel stays
// mounted and only the inactive ones are hidden.
//
// And hiding two of three scopes hides which of them carry a stored override,
// which is the first thing this screen is opened to find out. That has to ride
// on the tab itself.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import type { QuotaLimitsPayload } from "@/types/auth.types";

import { WorkspaceQuotaCard } from "./WorkspaceQuotaCard";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let tab = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/admin/settings/quota",
  useSearchParams: () => new URLSearchParams(tab ? `tab=${tab}` : "")
}));
vi.mock("@/hooks/usePermissions", () => ({ usePermissions: () => ({ isSuperuser: false }) }));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), apiError: vi.fn(), error: vi.fn(), warning: vi.fn() }
}));

const NONE: QuotaLimitsPayload = {
  requests_per_minute: null,
  heavy_per_day: null,
  concurrent_heavy: null,
  max_upload_bytes: null,
  max_items_per_request: null
};
const PLAN: QuotaLimitsPayload = {
  requests_per_minute: 600,
  heavy_per_day: 500,
  concurrent_heavy: 4,
  max_upload_bytes: 10 * 1024 * 1024,
  max_items_per_request: 500
};

const USAGE = {
  plan_slug: "verified",
  workspace_id: 42,
  scopes: [
    {
      scope: "workspace",
      requests_per_minute: 600,
      requests_used: 12,
      requests_reset_in: 40,
      heavy_per_day: 500,
      heavy_used: 1,
      heavy_reset_in: 3600,
      concurrent_heavy: 4,
      concurrent_used: 0,
      max_upload_bytes: 10 * 1024 * 1024,
      max_items_per_request: 500
    }
  ],
  // Two scopes carry a row, the key scope inherits.
  policy: [
    { scope: "workspace", override: { ...NONE, requests_per_minute: 400 }, inherited: PLAN },
    { scope: "key", override: NONE, inherited: PLAN },
    { scope: "session", override: { ...NONE, heavy_per_day: 50 }, inherited: PLAN }
  ]
};

let root: Root;
// One client for the whole test: swapping it mid-test would empty the cache and
// unmount the panels, which is the very thing a tab switch must not do.
let client: QueryClient;

async function settle() {
  for (let i = 0; i < 20; i += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

/** Render (or re-render into the same root, which preserves panel state). */
async function render() {
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <WorkspaceQuotaCard workspaceId={42} />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
}

/** One dimension's input in each scope panel, in tab order. */
function fields(dimension: string): HTMLInputElement[] {
  return [...document.body.querySelectorAll("input")].filter((el) =>
    el.id.endsWith(`-${dimension}`)
  );
}

/** The panel wrapper a field sits in, so its `hidden` state can be read. */
function panelOf(input: HTMLInputElement): HTMLElement {
  const panel = input.closest("section > div");
  if (!panel) throw new Error("no panel wrapper");
  return panel as HTMLElement;
}

const setValue = Object.getOwnPropertyDescriptor(
  window.HTMLInputElement.prototype,
  "value"
)!.set!;

beforeEach(() => {
  document.body.innerHTML = "";
  const container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  tab = "";
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => USAGE })
  );
});

describe("WorkspaceQuotaCard", () => {
  it("opens the scope named by ?tab= and hides the other two", async () => {
    tab = "session";
    await render();

    const [workspace, key, session] = fields("heavy_per_day").map(panelOf);
    expect(session.hidden).toBe(false);
    expect(workspace.hidden).toBe(true);
    expect(key.hidden).toBe(true);
    // The session row stores 50; the visible panel is the one that shows it.
    expect(fields("heavy_per_day")[2].value).toBe("50");
  });

  it("keeps a half-typed override when another scope is opened", async () => {
    await render();

    const workspaceHeavy = fields("heavy_per_day")[0];
    await act(async () => {
      setValue.call(workspaceHeavy, "120");
      workspaceHeavy.dispatchEvent(new Event("input", { bubbles: true }));
    });

    tab = "key";
    await render();
    tab = "";
    await render();

    // Unsaved work, and nothing asked for it to be dropped.
    expect(fields("heavy_per_day")[0].value).toBe("120");
  });

  it("marks on the tab which scopes carry a row", async () => {
    await render();

    const tabs = [...document.body.querySelectorAll("a[data-admin-tab]")];
    const marked = tabs
      .filter((link) => link.textContent?.includes(en.quota.state.overridden))
      .map((link) => link.getAttribute("data-admin-tab"));
    expect(marked).toEqual(["workspace", "session"]);
    expect(tabs.map((link) => link.getAttribute("data-admin-tab"))).toEqual([
      "workspace",
      "key",
      "session"
    ]);
  });
});
