// @vitest-environment happy-dom
//
// The admin shell's landmark is the content column the skip link jumps to —
// not the inset around it, which also holds the breadcrumb header.
import { act, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import en from "@/i18n/messages/en.json";
import { SIDEBAR_COOKIE_NAMES } from "@/lib/site/sidebar-cookies";

import { AdminLayoutClient } from "./AdminLayoutClient";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/teams",
  useRouter: () => ({ push: vi.fn() })
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isLoaded: true, canAccessAdminRoute: () => true })
}));
vi.mock("@/stores/workspace.store", () => ({
  useWorkspaceStore: (selector: (state: { currentWorkspaceId: number | null }) => unknown) =>
    selector({ currentWorkspaceId: 1 })
}));
vi.mock("@/components/HoverPrefetchLink", () => ({
  HoverPrefetchLink: ({ href, children }: { href: string; children: ReactNode }) => <a href={href}>{children}</a>
}));
vi.mock("@/components/admin/AdminSidebar", () => ({ AdminSidebar: () => <nav aria-label="Admin" /> }));

async function mount() {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <QueryClientProvider client={new QueryClient()}>
          <AdminLayoutClient defaultSidebarOpen>
            <p data-testid="page">page</p>
            <input data-testid="field" />
          </AdminLayoutClient>
        </QueryClientProvider>
      </NextIntlClientProvider>
    );
  });
  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    }
  };
}

describe("AdminLayoutClient", () => {
  it("makes the content column the one main landmark, the header outside it", async () => {
    const { container, unmount } = await mount();

    const mains = container.querySelectorAll("main");
    expect(mains).toHaveLength(1);
    expect(mains[0].id).toBe("admin-content");
    expect(mains[0].querySelector('[data-testid="page"]')).not.toBeNull();
    expect(mains[0].querySelector("header")).toBeNull();
    expect(container.querySelector('a[href="#admin-content"]')).not.toBeNull();
    expect(container.querySelector(`nav[aria-label="${en.kit.ui.breadcrumb}"]`)).not.toBeNull();

    unmount();
  });

  it("leaves Ctrl+B to a focused field and toggles the sidebar everywhere else", async () => {
    const { container, unmount } = await mount();
    const cookie = `${SIDEBAR_COOKIE_NAMES.admin}=false`;
    const press = (target: EventTarget) =>
      act(() => {
        target.dispatchEvent(new KeyboardEvent("keydown", { key: "b", ctrlKey: true, bubbles: true }));
      });

    press(container.querySelector('[data-testid="field"]')!);
    expect(document.cookie).not.toContain(cookie);

    press(document.body);
    expect(document.cookie).toContain(cookie);

    unmount();
  });
});
