// @vitest-environment happy-dom
//
// The unresolved-names queue after P5-1. What is pinned here:
//  1. the superuser gate — a reader sees the queue but no way to act on it,
//     rather than controls that fail on submit;
//  2. `?type=` is the type filter's only store: read on mount, written by the
//     chip, so a link to "just the maps" opens on just the maps;
//  3. one attach end to end — pick the entity the raw name meant, press
//     Attach, and the alias goes to that entity;
//  4. seven columns do not fit a phone, so rows render as cards below `md` —
//     and the card keeps the target picker, without which Attach could never
//     be armed there.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, useEffect, useState, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import UnresolvedNamesPage from "./page";
import type { CatalogAliasMissRead } from "@/types/admin.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const getCatalogAliasMisses = vi.fn();
const attachCatalogAlias = vi.fn();
const dismissCatalogAliasMiss = vi.fn();
const getHeroes = vi.fn();
const getMaps = vi.fn();
const getGamemodes = vi.fn();

let superuser = true;

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ dateTime: (value: Date) => value.toISOString() })
}));
vi.mock("@/hooks/usePermissions", () => ({
  usePermissions: () => ({ isSuperuser: superuser, isLoaded: true })
}));
vi.mock("@/services/admin.service", () => ({
  default: {
    getCatalogAliasMisses: (...args: unknown[]) => getCatalogAliasMisses(...args),
    attachCatalogAlias: (...args: unknown[]) => attachCatalogAlias(...args),
    dismissCatalogAliasMiss: (...args: unknown[]) => dismissCatalogAliasMiss(...args),
    getHeroes: (...args: unknown[]) => getHeroes(...args),
    getMaps: (...args: unknown[]) => getMaps(...args),
    getGamemodes: (...args: unknown[]) => getGamemodes(...args)
  }
}));
vi.mock("@/lib/notify", () => ({
  notify: { success: vi.fn(), error: vi.fn(), apiError: vi.fn() }
}));

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  rerender?.();
});

let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/content/unresolved",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(window.location.search)
}));

const MISS: CatalogAliasMissRead = {
  id: 3,
  entity_type: "map",
  raw_name: "Ilios2",
  occurrences: 47,
  first_seen_at: "2026-08-01T10:00:00Z",
  last_seen_at: "2026-08-30T18:20:00Z",
  last_log_record_id: 991,
  last_log_tournament_id: 7,
  resolved_at: null
};

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
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  return <>{render()}</>;
}

/** `useIsMobile` reads `innerWidth`; `matchMedia` only carries its listener. */
function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  window.matchMedia = ((query: string) => ({
    matches: width < 768,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
}

async function mount(search = "") {
  window.history.replaceState(null, "", `/admin/content/unresolved${search}`);
  const container = document.createElement("div");
  document.body.appendChild(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const root = createRoot(container);
  mounted.push({ root, container });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness render={() => <UnresolvedNamesPage />} />
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
  await settle(4);
}

function commandItem(label: string) {
  return Array.from(document.querySelectorAll('[cmdk-item=""]')).find((item) =>
    item.textContent?.trim().startsWith(label)
  );
}

function button(label: string) {
  return Array.from(document.querySelectorAll("button")).find(
    (candidate) => candidate.textContent?.trim() === label
  );
}

/** `entity_type` of the most recent queue request. */
function lastEntityType(): unknown {
  return (getCatalogAliasMisses.mock.calls.at(-1)?.[0] as { entity_type?: unknown } | undefined)
    ?.entity_type;
}

beforeEach(() => {
  superuser = true;
  setViewportWidth(1280);
  replace.mockClear();
  getCatalogAliasMisses
    .mockReset()
    .mockResolvedValue({ results: [MISS], total: 1, page: 1, per_page: 25 });
  attachCatalogAlias.mockReset().mockResolvedValue(undefined);
  dismissCatalogAliasMiss.mockReset().mockResolvedValue(undefined);
  getHeroes.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: 200 });
  getGamemodes.mockReset().mockResolvedValue({ results: [], total: 0, page: 1, per_page: 200 });
  getMaps.mockReset().mockResolvedValue({
    results: [{ id: 12, name: "Ilios", gamemode: null }],
    total: 1,
    page: 1,
    per_page: 200
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

describe("admin Game content › Unresolved names", () => {
  it("shows the queue but no triage controls without superuser", async () => {
    superuser = false;
    const container = await mount();

    expect(container.textContent).toContain("Ilios2");
    expect(container.querySelector('[aria-label="Pick a map…"]')).toBeNull();
    expect(button("Attach")).toBeUndefined();
  });

  it("gives a superuser the target picker and the inline actions", async () => {
    const container = await mount();

    expect(container.querySelector('[aria-label="Pick a map…"]')).not.toBeNull();
    expect(button("Attach")).toBeDefined();
  });

  it("reads ?type= on mount", async () => {
    await mount("?type=hero");

    expect(lastEntityType()).toBe("hero");
  });

  it("writes ?type= when the chip is picked, and refetches", async () => {
    const container = await mount();
    expect(lastEntityType()).toBeUndefined();

    await click(container.querySelector('[aria-label="Add filter"]'));
    await click(commandItem("Type"));
    await click(commandItem("Map"));

    expect(window.location.search).toContain("type=map");
    expect(lastEntityType()).toBe("map");
  });

  it("attaches the raw name to the entity picked in the row", async () => {
    const container = await mount();

    // Nothing picked yet, so the action is inert rather than silently failing.
    expect(button("Attach")).toHaveProperty("disabled", true);

    await click(container.querySelector('[aria-label="Pick a map…"]'));
    await click(commandItem("Ilios"));
    await click(button("Attach"));

    expect(attachCatalogAlias).toHaveBeenCalledWith({
      entity_type: "map",
      entity_id: 12,
      alias: "Ilios2"
    });
  });

  it("renders rows as cards below md, keeping the target picker", async () => {
    setViewportWidth(375);
    const container = await mount();

    const cards = container.querySelectorAll("ul[aria-label='Rows'] > li");
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Ilios2");
    expect(cards[0].querySelector('[aria-label="Pick a map…"]')).not.toBeNull();
  });
});
