// @vitest-environment happy-dom
//
// The rank collector, first of the three screens the collectors hub replaced.
// What is pinned:
//
//  1. `rank.read` is the PAGE's gate, not the sidebar's — a typed URL has to be
//     refused, and nothing may be asked of the API before it is allowed;
//  2. the slot comes from `?tab=`, in both directions. This is the whole point
//     of the move: the old screen kept the tab in `useState`, so Settings had no
//     URL at all and could not be linked or bookmarked. A slot the viewer may
//     not have (Settings, superuser-only) falls back to the first visible one
//     instead of rendering an empty page — and health plus the fetch log are
//     that one slot, so an old `?tab=history` link still lands on the log;
//  3. one manual action end to end — Pause collection reads the setting and
//     writes it back with `enabled` flipped, rather than posting a bare `false`
//     that would drop the interval and rate limit stored beside it;
//  4. streams stays global-only. Rank and subscriptions are workspace-scoped,
//     streams is not (one poller, one Redis key), and the route table is where
//     that difference is declared — asserted here because this WU is what put
//     the three behind one hub and made it easy to level them by accident.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getMatchingAdminRoute } from "@/components/admin/admin-navigation";
import en from "@/i18n/messages/en.json";
import RankCollectorPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getRankCollectionStats = vi.fn();
const getRankFetchLog = vi.fn();
const getSetting = vi.fn();
const updateSetting = vi.fn();

let granted: string[] = ["rank.read"];
let superuser = false;

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string) => superuser || granted.includes(permission),
    isSuperuser: superuser,
    isLoaded: true
  })
}));

vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ user: { isSuperuser: superuser } })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number | null }) => unknown) =>
    selector({ currentWorkspaceId: 3 })
}));

vi.mock("@/services/admin.service", () => ({
  default: {
    getRankCollectionStats: (...args: unknown[]) => getRankCollectionStats(...args),
    getRankFetchLog: (...args: unknown[]) => getRankFetchLog(...args),
    getSetting: (...args: unknown[]) => getSetting(...args),
    updateSetting: (...args: unknown[]) => updateSetting(...args),
    reenableDisabledRankCollection: vi.fn()
  }
}));

// The config form itself is the panel's contract (and 45 OW ranks' worth of
// rendering); what this page owes is mounting it for the right slot.
vi.mock("@/components/admin/collectors/rank-settings", () => ({
  RankSettingsPanel: () => <p>rank settings panel</p>
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn(), warning: vi.fn() }
}));

let rerender: (() => void) | null = null;
const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/collectors/rank",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

// A tab is a link; clicking it is a navigation, which in the app is Next's
// router and here is the same `replace` the harness re-renders on.
vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a
      href={href}
      {...rest}
      onClick={(event) => {
        event.preventDefault();
        replace(href);
      }}
    >
      {children}
    </a>
  )
}));

const STATS = {
  total: 120,
  never_checked: 4,
  by_status: {
    ok: 100,
    pending: 5,
    not_found: 6,
    private: 3,
    error: 4,
    rate_limited: 0,
    disabled: 2
  },
  tier0: 1,
  tier1: 2,
  tier2: 3,
  coverage_24h: 90,
  coverage_7d: 118,
  // Fresh on purpose: the health screen now calls a collector with no recent
  // success "down", so a hardcoded past date would put every other case in this
  // file behind an outage banner.
  last_success_at: new Date(Date.now() - 60_000).toISOString(),
  fetch_24h: {
    ok: 200,
    pending: 0,
    not_found: 6,
    private: 1,
    error: 3,
    rate_limited: 0,
    disabled: 0
  },
  fetch_24h_total: 210,
  error_rate_24h: 0.02,
  enabled: true,
  scope: "workspace",
  interval_seconds: 3600,
  rate_limit_per_minute: 30,
  overfast_base_url: "https://overfast.craazzzyyfoxx.me",
  overfast_circuit_state: "closed",
  invalid_battle_tags_24h: 0
};

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 8) {
  for (let turn = 0; turn < turns; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
}

function Harness() {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <RankCollectorPage />;
}

async function mount(search = "") {
  window.history.replaceState(null, "", `/admin/collectors/rank${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <Harness />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  await settle();
  return container;
}

async function click(element: Element | null | undefined) {
  expect(element).toBeTruthy();
  await act(async () => {
    element!.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
  await settle(4);
}

function tab(container: HTMLElement, label: string) {
  return Array.from(container.querySelectorAll("a[data-admin-tab]")).find(
    (link) => link.textContent?.trim() === label
  );
}

function button(container: HTMLElement, text: string) {
  return Array.from(container.querySelectorAll("button")).find(
    (element) => element.textContent?.trim() === text
  );
}

beforeEach(() => {
  document.body.innerHTML = "";
  granted = ["rank.read"];
  superuser = false;
  replace.mockClear();
  getRankCollectionStats.mockReset().mockResolvedValue(STATS);
  getRankFetchLog.mockReset().mockResolvedValue([
    {
      id: 1,
      created_at: "2026-09-03T09:00:00Z",
      battle_tag: "Anak#2107",
      status: "ok",
      source: "scheduled",
      snapshots_written: 2,
      error: null,
      user_id: 42
    }
  ]);
  getSetting.mockReset().mockResolvedValue({
    key: "parser.rank_collection",
    value: { enabled: true, interval_seconds: 3600, rate_limit_per_minute: 30 }
  });
  updateSetting.mockReset().mockResolvedValue({ key: "parser.rank_collection", value: {} });
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
});

describe("RankCollectorPage", () => {
  it("refuses the screen without rank.read, before asking the API anything", async () => {
    granted = [];
    const container = await mount();

    expect(container.textContent).toContain("rank.read");
    expect(getRankCollectionStats).not.toHaveBeenCalled();
    expect(getRankFetchLog).not.toHaveBeenCalled();
    // No tab bar either: there is nothing behind any of the slots.
    expect(container.querySelectorAll("a[data-admin-tab]")).toHaveLength(0);
  });

  it("shows health and the fetch log on one screen; an old ?tab=history link lands there", async () => {
    const container = await mount("?tab=history");

    expect(getRankCollectionStats).toHaveBeenCalled();
    expect(getRankFetchLog).toHaveBeenCalled();
    expect(container.textContent).toContain("Task history");
    // Status is the only slot a non-superuser has, so there is no tab bar to
    // pick it from — a one-tab bar would be a heading with a hover state.
    expect(container.querySelectorAll("a[data-admin-tab]")).toHaveLength(0);
  });

  // The September 2026 OverFast outage: the upstream host stopped resolving, the
  // circuit opened, and this screen kept reading healthy for a day — the error
  // ratio FALLS when fetches stop happening, so every tile agreed nothing was
  // wrong. A stopped collector has to say so on the screen, not only in a metric.
  it("says battle-tag parsing is down when the upstream circuit is open", async () => {
    getRankCollectionStats.mockResolvedValue({
      ...STATS,
      overfast_circuit_state: "open",
      // Unchanged from the healthy fixture on purpose: a clean error ratio must
      // not be able to hide a dead upstream.
      error_rate_24h: 0.02
    });

    const container = await mount();

    const alert = container.querySelector("[role=alert]");
    expect(alert?.textContent).toContain("Battle-tag rank parsing is down");
    expect(alert?.textContent).toContain("overfast.craazzzyyfoxx.me");
  });

  it("says the same when nothing has been collected for half an hour", async () => {
    getRankCollectionStats.mockResolvedValue({
      ...STATS,
      last_success_at: new Date(Date.now() - 45 * 60_000).toISOString()
    });

    const container = await mount();

    expect(container.querySelector("[role=alert]")?.textContent).toContain(
      "Battle-tag rank parsing is down"
    );
  });

  it("stays quiet while collection is healthy", async () => {
    const container = await mount();

    expect(container.querySelector("[role=alert]")).toBeNull();
  });

  it("defaults to Status and writes the slot to the URL when a tab is clicked", async () => {
    superuser = true;
    const container = await mount();

    expect(tab(container, "Status")?.getAttribute("aria-current")).toBe("page");
    expect(container.textContent).not.toContain("rank settings panel");

    await click(tab(container, "Settings"));

    expect(replace).toHaveBeenCalledWith("/admin/collectors/rank?tab=settings");
    expect(window.location.search).toBe("?tab=settings");
    expect(container.textContent).toContain("rank settings panel");
  });

  it("hides the superuser-only Settings slot and falls back rather than blanking", async () => {
    const container = await mount("?tab=settings");

    expect(tab(container, "Settings")).toBeUndefined();
    expect(container.textContent).not.toContain("rank settings panel");
    expect(getRankCollectionStats).toHaveBeenCalled();
  });

  it("offers Settings to a superuser on the same ?tab=", async () => {
    superuser = true;
    const container = await mount("?tab=settings");

    expect(tab(container, "Settings")?.getAttribute("aria-current")).toBe("page");
    expect(container.textContent).toContain("rank settings panel");
  });

  it("pauses collection by flipping `enabled` on the stored setting, keeping its siblings", async () => {
    superuser = true;
    const container = await mount();

    await click(button(container, "Pause collection"));

    expect(getSetting).toHaveBeenCalledWith("parser.rank_collection");
    expect(updateSetting).toHaveBeenCalledWith("parser.rank_collection", {
      value: { enabled: false, interval_seconds: 3600, rate_limit_per_minute: 30 }
    });
  });

  it("keeps streams global-only while its two siblings stay workspace-scoped", () => {
    expect(getMatchingAdminRoute("/admin/collectors/streams")?.globalOnly).toBe(true);
    expect(getMatchingAdminRoute("/admin/collectors/streams")?.permissions).toEqual([
      "stream.read"
    ]);
    expect(getMatchingAdminRoute("/admin/collectors/rank")?.globalOnly).toBeUndefined();
    expect(getMatchingAdminRoute("/admin/collectors/subscriptions")?.globalOnly).toBeUndefined();
  });
});
