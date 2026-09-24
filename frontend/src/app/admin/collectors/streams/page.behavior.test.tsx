// @vitest-environment happy-dom
//
// The stream collector is the thin member of the trio, and that is the point
// being pinned: it has no check log, so its bar carries two slots — not three
// with History greyed out. The other half is its gate: the poller is
// platform-wide, so `stream.read` is asked for in its GLOBAL form and a
// workspace-scoped grant is refused with a reason instead of an empty page.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import StreamCollectorPage from "./page";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getStreamPollHealth = vi.fn();

let globalGrants: string[] = ["stream.read"];
let workspaceGrants: string[] = [];
let superuser = false;

vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({
    canAccessPermission: (permission: string, workspaceId?: number | null) =>
      superuser ||
      (workspaceId === null
        ? globalGrants.includes(permission)
        : globalGrants.includes(permission) || workspaceGrants.includes(permission)),
    isSuperuser: superuser,
    isLoaded: true
  })
}));

vi.mock("@/hooks/useAuthProfile", () => ({
  useAuthProfile: () => ({ user: { isSuperuser: superuser } })
}));

vi.mock("@/services/admin.service", () => ({
  default: {
    getStreamPollHealth: (...args: unknown[]) => getStreamPollHealth(...args),
    getSetting: vi.fn(),
    updateSetting: vi.fn()
  }
}));

vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn(), warning: vi.fn() }
}));

// The settings form is `CollectionSettingsPanel`'s contract, not this page's.
vi.mock("@/components/admin/collectors/stream-settings", () => ({
  StreamSettingsPanel: () => <p>stream settings panel</p>
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/collectors/streams",
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

vi.mock("next/link", () => ({
  default: ({ href, children, ...rest }: { href: string; children: ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  )
}));

const mounted: { root: Root; container: HTMLElement }[] = [];

async function mount(search = "") {
  window.history.replaceState(null, "", `/admin/collectors/streams${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={client}>
          <StreamCollectorPage />
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  for (let turn = 0; turn < 8; turn += 1) {
    await act(async () => {
      const { promise, resolve } = Promise.withResolvers<void>();
      setTimeout(resolve, 0);
      await promise;
    });
  }
  return container;
}

beforeEach(() => {
  document.body.innerHTML = "";
  globalGrants = ["stream.read"];
  workspaceGrants = [];
  superuser = false;
  getStreamPollHealth.mockReset().mockResolvedValue({
    enabled: true,
    interval_seconds: 60,
    batch_size: 100,
    status: "ok",
    last_run_at: "2026-09-03T09:00:00Z",
    tournaments_active: 2,
    tournaments_updated: 1,
    channels_polled: 5,
    live_channels: 1,
    ratelimit_remaining: 700,
    credentials_configured: true
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

describe("StreamCollectorPage", () => {
  it("offers Status and Settings only — there is no check log to put behind a History slot", async () => {
    superuser = true;
    const container = await mount();

    expect(
      Array.from(container.querySelectorAll("a[data-link-tab]")).map((link) =>
        link.getAttribute("data-link-tab")
      )
    ).toEqual(["status", "settings"]);
  });

  it("shows no tab bar to a non-superuser, and opens the poller health directly", async () => {
    const container = await mount();

    // Status would be the only slot; a one-tab bar is noise, so it is omitted.
    expect(container.querySelectorAll("a[data-link-tab]")).toHaveLength(0);
    expect(getStreamPollHealth).toHaveBeenCalled();
    expect(container.textContent).toContain("Last tick OK");
  });

  it("refuses a workspace-scoped stream.read holder: the poller is platform-wide", async () => {
    globalGrants = [];
    workspaceGrants = ["stream.read"];
    const container = await mount();

    expect(container.textContent).toContain("global stream.read");
    expect(getStreamPollHealth).not.toHaveBeenCalled();
  });
});
