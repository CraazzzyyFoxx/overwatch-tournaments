// @vitest-environment happy-dom
//
// The Game content shell (P5-1, F13). What is pinned here:
//  1. all four sections are tabs of one screen — three catalogues plus the
//     triage queue that works on them;
//  2. the path segment picks the active tab, so a deep link lands marked;
//  3. the queue badge carries its length, and an empty queue shows no badge:
//     a zero would read as a number worth acting on.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GameContentLayout from "./layout";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getCatalogAliasMisses = vi.fn();
let pathname = "/admin/content/heroes";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  useSearchParams: () => new URLSearchParams()
}));
vi.mock("@/services/admin.service", () => ({
  default: { getCatalogAliasMisses: (...args: unknown[]) => getCatalogAliasMisses(...args) }
}));

const mounted: { root: Root; container: HTMLElement }[] = [];

async function settle(turns = 6) {
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
        <GameContentLayout>
          <p>section body</p>
        </GameContentLayout>
      </QueryClientProvider>
    );
  });
  await settle();
  return container;
}

function tab(container: HTMLElement, key: string) {
  return container.querySelector<HTMLAnchorElement>(`a[data-link-tab="${key}"]`);
}

beforeEach(() => {
  pathname = "/admin/content/heroes";
  getCatalogAliasMisses.mockReset().mockResolvedValue({
    results: [],
    total: 12,
    page: 1,
    per_page: 1
  });
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

describe("admin Game content layout", () => {
  it("renders the four sections as tabs of one screen", async () => {
    const container = await mount();

    expect(
      Array.from(container.querySelectorAll("a[data-link-tab]")).map((link) =>
        link.getAttribute("href")
      )
    ).toEqual([
      "/admin/content/heroes",
      "/admin/content/maps",
      "/admin/content/gamemodes",
      "/admin/content/unresolved"
    ]);
    expect(container.textContent).toContain("section body");
  });

  it("marks the tab named by the path", async () => {
    pathname = "/admin/content/unresolved";
    const container = await mount();

    expect(tab(container, "unresolved")?.getAttribute("aria-current")).toBe("page");
    expect(tab(container, "heroes")?.getAttribute("aria-current")).toBeNull();
  });

  it("badges the queue with how much is waiting", async () => {
    const container = await mount();

    expect(getCatalogAliasMisses).toHaveBeenCalledWith({
      page: 1,
      per_page: 1,
      include_resolved: false
    });
    expect(tab(container, "unresolved")?.textContent).toContain("12");
  });

  it("drops the badge when the queue is empty", async () => {
    getCatalogAliasMisses.mockResolvedValue({ results: [], total: 0, page: 1, per_page: 1 });
    const container = await mount();

    expect(tab(container, "unresolved")?.textContent?.trim()).toBe("Unresolved names");
  });
});
