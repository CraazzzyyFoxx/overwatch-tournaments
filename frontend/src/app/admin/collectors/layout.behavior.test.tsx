// @vitest-environment happy-dom
//
// The collectors tab bar (F14 ·1). Two things it must get right:
//
//  1. the health dot. Putting three pollers on one screen is only worth it if
//     the bar reports the two you are NOT looking at, and the marker must not
//     be colour alone — every dot carries a word, rendered `sr-only` by
//     `LinkTabs`;
//  2. who sees which tab. Rank and subscriptions are workspace-scoped, streams
//     is global (one poller, one Redis key), so a holder whose `stream.read`
//     is a workspace grant must not be offered it — and the bar must not fire
//     the health request that would 403 either.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import CollectorsLayout from "./layout";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getRankCollectionStats = vi.fn();
const getSubscriptionCollectionStats = vi.fn();
const getStreamPollHealth = vi.fn();

/** Grants keyed the way `canAccessPermission(permission, workspaceId)` asks:
 *  `null` is the global form, anything else the workspace-scoped one. */
let globalGrants: string[] = [];
let workspaceGrants: string[] = [];

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string, workspaceId?: number | null) =>
      workspaceId === null
        ? globalGrants.includes(permission)
        : globalGrants.includes(permission) || workspaceGrants.includes(permission),
    isSuperuser: false,
    isLoaded: true
  })
}));

vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number | null }) => unknown) =>
    selector({ currentWorkspaceId: 3 })
}));

vi.mock("@/services/admin.service", () => ({
  default: {
    getRankCollectionStats: (...args: unknown[]) => getRankCollectionStats(...args),
    getSubscriptionCollectionStats: (...args: unknown[]) =>
      getSubscriptionCollectionStats(...args),
    getStreamPollHealth: (...args: unknown[]) => getStreamPollHealth(...args)
  }
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/collectors/rank"
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

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

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <CollectorsLayout>
          <p>slot</p>
        </CollectorsLayout>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

function tab(container: HTMLElement, label: string) {
  return Array.from(container.querySelectorAll("a[data-link-tab]")).find((link) =>
    link.textContent?.includes(label)
  );
}

function tabKeys(container: HTMLElement) {
  return Array.from(container.querySelectorAll("a[data-link-tab]")).map((link) =>
    link.getAttribute("data-link-tab")
  );
}

beforeEach(() => {
  document.body.innerHTML = "";
  globalGrants = [];
  workspaceGrants = ["rank.read", "subscription.read"];
  getRankCollectionStats
    .mockReset()
    .mockResolvedValue({ enabled: true, error_rate_24h: 0.01, by_status: { disabled: 0 } });
  getSubscriptionCollectionStats
    .mockReset()
    .mockResolvedValue({ enabled: false, error_rate_24h: 0, by_state: { error: 0 } });
  getStreamPollHealth.mockReset().mockResolvedValue({
    enabled: true,
    credentials_configured: true,
    status: "ok"
  });
});

afterEach(async () => {
  await act(async () => {
    for (const { root, container } of mounted.splice(0)) {
      root.unmount();
      container.remove();
    }
  });
});

describe("CollectorsLayout", () => {
  it("marks each collector's health with a word, not just a colour", async () => {
    globalGrants = ["stream.read"];
    const container = await mount();

    expect(tab(container, "Rank")?.textContent).toContain("Healthy");
    // Paused outranks the (clean) error rate: it explains every other number.
    expect(tab(container, "Subscriptions")?.textContent).toContain("Paused");
    expect(tab(container, "Streams")?.textContent).toContain("Last tick OK");
    // The word is for screen readers; the dot itself carries no text.
    expect(tab(container, "Rank")?.querySelector(".sr-only")?.textContent).toBe("Healthy");
  });

  it("hides Streams from a workspace-scoped stream.read holder and asks nothing of the poller", async () => {
    workspaceGrants = ["rank.read", "subscription.read", "stream.read"];
    const container = await mount();

    expect(tabKeys(container)).toEqual(["rank", "subscriptions"]);
    expect(getStreamPollHealth).not.toHaveBeenCalled();
    expect(getRankCollectionStats).toHaveBeenCalled();
  });

  it("shows only the collectors the viewer can read", async () => {
    workspaceGrants = ["rank.read"];
    const container = await mount();

    expect(tabKeys(container)).toEqual(["rank"]);
    expect(getSubscriptionCollectionStats).not.toHaveBeenCalled();
    expect(getStreamPollHealth).not.toHaveBeenCalled();
  });
});
