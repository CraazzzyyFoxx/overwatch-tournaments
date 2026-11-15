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
const listCatalogEntities = vi.fn();

let superuser = true;

vi.mock("next-intl", async () => {
  const importedMessages = await import("@/i18n/messages/en.json");
  const { en: kitMessages } = await import("@craazzzyyfoxx/admin-kit/messages");
  const messages = { ...(importedMessages.default ?? importedMessages), ...kitMessages };
  return {
    useTranslations: (namespace: string) => {
      const lookup = (key: string) => {
        let value: unknown = messages;
        for (const part of `${namespace}.${key}`.split(".")) {
          if (value == null) return undefined;
          value = (value as Record<string, unknown>)[part];
        }
        return typeof value === "string" ? value : undefined;
      };
      const t = (key: string, values?: Record<string, unknown>) =>
        lookup(key)?.replace(/\{(\w+)\}/g, (_, name) => String(values?.[name] ?? `{${name}}`)) ?? key;
      t.has = (key: string) => lookup(key) !== undefined;
      return t;
    }
  };
});
vi.mock("@/lib/datetime/client", () => ({
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
    listCatalogEntities: (...args: unknown[]) => listCatalogEntities(...args)
  }
}));
vi.mock("@/services/discipline.service", () => ({
  default: {
    list: async () => [
      { code: "overwatch", name: "Overwatch", enabled: true, kinds: { character: "Hero", map: "Map", mode: "Mode" } },
      { code: "lol", name: "League of Legends", enabled: true, kinds: { character: "Champion", map: "Map" } }
    ]
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
  discipline: "overwatch",
  kind: "map",
  raw_name: "Ilios2",
  occurrences: 47,
  first_seen_at: "2026-08-01T10:00:00Z",
  last_seen_at: "2026-08-30T18:20:00Z",
  last_ingest_job_id: 991,
  last_log_tournament_id: 7,
  resolved_at: null
};

const NONENTITY: CatalogAliasMissRead[] = [
  { ...MISS, id: 4, kind: "stat", raw_name: "no_such_stat" },
  { ...MISS, id: 5, kind: "event", raw_name: "no_such_event" },
  { ...MISS, id: 6, kind: "role", raw_name: "player_role:ghost", last_ingest_job_id: null }
];

const mounted: { root: Root; container: HTMLElement }[] = [];
let client: QueryClient;

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
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
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

/** Dismiss is icon-only: found by its accessible name. */
function dismissButtons() {
  return Array.from(document.querySelectorAll('button[aria-label="Dismiss"]'));
}

/** `kind` of the most recent queue request. */
function lastKind(): unknown {
  return (getCatalogAliasMisses.mock.calls.at(-1)?.[0] as { kind?: unknown } | undefined)?.kind;
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
  // Targets are read per (discipline, kind) of the miss itself.
  listCatalogEntities.mockReset().mockImplementation(async (discipline: string, kind: string) => {
    const results =
      discipline === "overwatch" && kind === "map"
        ? [{ id: 12, name: "Ilios", parent: { id: 3, name: "Control" } }]
        : discipline === "lol" && kind === "character"
          ? [
              { id: 501, name: "Ahri", parent: null },
              { id: 502, name: "Zed", parent: null }
            ]
          : [];
    return { results, total: results.length, page: 1, per_page: -1 };
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

  it("gives a superuser the target picker and the inline dismiss", async () => {
    const container = await mount();

    expect(container.querySelector('[aria-label="Pick a map…"]')).not.toBeNull();
    expect(dismissButtons()).toHaveLength(1);
  });

  it("reads ?type= on mount", async () => {
    await mount("?type=character");

    expect(lastKind()).toBe("character");
  });

  it("writes ?type= when the chip is picked, and refetches", async () => {
    const container = await mount();
    expect(lastKind()).toBeUndefined();

    await click(container.querySelector('[aria-label="Add filter"]'));
    await click(commandItem("Type"));
    await click(commandItem("Stat"));

    expect(window.location.search).toContain("type=stat");
    expect(lastKind()).toBe("stat");
  });

  it("attaches the raw name to the entity picked in the row", async () => {
    const container = await mount();

    // Nothing picked yet: Attach is there but disabled, saying what to pick.
    const blocked = button("Attach");
    expect(blocked?.disabled).toBe(true);
    const reason = document.getElementById(blocked?.getAttribute("aria-describedby") ?? "");
    expect(reason?.textContent).toBe("Pick the map this name means first");

    await click(container.querySelector('[aria-label="Pick a map…"]'));
    await click(commandItem("Ilios"));
    await click(button("Attach"));

    expect(attachCatalogAlias).toHaveBeenCalledWith({ entity_id: 12, alias: "Ilios2" });
  });

  it("does not pin the queue to a discipline", async () => {
    await mount();

    expect(getCatalogAliasMisses.mock.calls.at(-1)?.[0]).not.toHaveProperty("discipline");
  });

  it("shows stat, event and role misses by domain and code with dismiss as the only action", async () => {
    getCatalogAliasMisses.mockResolvedValue({ results: NONENTITY, total: 3, page: 1, per_page: 25 });
    const container = await mount();

    for (const text of ["no_such_stat", "no_such_event", "player_role:ghost", "overwatch", "Stat", "Event", "Role"]) {
      expect(container.textContent).toContain(text);
    }
    expect(container.querySelector('[aria-label^="Pick a"]')).toBeNull();
    expect(button("Attach")).toBeUndefined();
    expect(dismissButtons()).toHaveLength(3);
    expect(container.textContent).toContain("Dismiss only");
    expect(listCatalogEntities).not.toHaveBeenCalled();
  });

  it("dismisses a nonentity miss without creating an alias", async () => {
    getCatalogAliasMisses.mockResolvedValue({ results: [NONENTITY[2]], total: 1, page: 1, per_page: 25 });
    await mount();

    await click(dismissButtons()[0]);

    expect(dismissCatalogAliasMiss).toHaveBeenCalledWith(6);
    expect(attachCatalogAlias).not.toHaveBeenCalled();
  });

  it("loads attach targets by the miss's own discipline and kind, never another game's", async () => {
    getCatalogAliasMisses.mockResolvedValue({
      results: [{ ...MISS, id: 9, discipline: "lol", kind: "character", raw_name: "Ahri2" }],
      total: 1,
      page: 1,
      per_page: 25
    });
    const container = await mount();

    expect(container.textContent).toContain("lol");
    expect(listCatalogEntities.mock.calls.map((call) => call.slice(0, 2))).toEqual([["lol", "character"]]);
    // The game's own word for the kind: a League miss asks for a champion.
    expect(container.querySelector('[aria-label="Pick a champion…"]')).not.toBeNull();
  });

  it("attaches a League of Legends alias to the champion picked, and refreshes only that game's characters", async () => {
    getCatalogAliasMisses.mockResolvedValue({
      results: [{ ...MISS, id: 9, discipline: "lol", kind: "character", raw_name: "Ahri2" }],
      total: 1,
      page: 1,
      per_page: 25
    });
    const container = await mount();
    const invalidate = vi.spyOn(client, "invalidateQueries");

    await click(container.querySelector('[aria-label="Pick a champion…"]'));
    await click(commandItem("Ahri"));
    await click(button("Attach"));

    expect(attachCatalogAlias).toHaveBeenCalledWith({ entity_id: 501, alias: "Ahri2" });
    // The miss's own game and kind — not the page's view, and not another game's characters.
    const keys = invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey));
    expect(keys).toContain(JSON.stringify(["catalog", "lol", "character"]));
    expect(keys.some((key) => key.includes("overwatch"))).toBe(false);
    expect(keys).not.toContain(JSON.stringify(["catalog", "lol", "map"]));
  });

  it("links the last ingest job to its hinted tournament", async () => {
    const container = await mount();

    const link = container.querySelector('a[href="/admin/tournaments/7/matches/logs"]');
    expect(link?.textContent).toBe("#991");
  });

  it("renders rows as cards below md, keeping the target picker", async () => {
    setViewportWidth(375);
    const container = await mount();

    const cards = container.querySelectorAll("ul[aria-label='Rows'] > li");
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("Ilios2");
    expect(cards[0].querySelector('[aria-label="Pick a map…"]')).not.toBeNull();
  });

  it("renders nonentity rows as dismiss-only cards below md", async () => {
    setViewportWidth(375);
    getCatalogAliasMisses.mockResolvedValue({ results: [NONENTITY[0]], total: 1, page: 1, per_page: 25 });
    const container = await mount();

    const cards = container.querySelectorAll("ul[aria-label='Rows'] > li");
    expect(cards).toHaveLength(1);
    expect(cards[0].textContent).toContain("no_such_stat");
    expect(cards[0].textContent).toContain("overwatch · Stat");
    expect(cards[0].querySelector('[aria-label^="Pick a"]')).toBeNull();
  });
});
