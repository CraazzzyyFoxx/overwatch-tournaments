// @vitest-environment happy-dom
//
// `usePlayerSearch` records every selection into localStorage-backed history
// shared by the header's combobox and the landing hero's. What is pinned here:
//  1. picking a result records it;
//  2. an empty query surfaces "Recent" once history has entries — the popover
//     mounts its content only while open, so this also proves history renders
//     independently of an active search;
//  3. picking the same player twice never duplicates the entry.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PlayerSearchCombobox } from "@/components/PlayerSearchCombobox";
import type { MinimizedUser } from "@/types/user.types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const HISTORY_KEY = "player-search-history";

const searchUsers = vi.fn();
const routerPush = vi.fn();

vi.mock("@/services/user.service", () => ({
  default: { searchUsers: (...args: unknown[]) => searchUsers(...args) }
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: (...args: unknown[]) => routerPush(...args) })
}));
// Labels come through as their message keys, so assertions read as the keys
// the component is contracted to use.
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

function user(overrides: Partial<MinimizedUser> = {}): MinimizedUser {
  return { id: 1, name: "Alice", ...overrides };
}

let container: HTMLDivElement;
let root: Root | undefined;

// Node 22 exposes its own `localStorage` that throws without
// `--localstorage-file`, and happy-dom does not shadow it. A per-test
// in-memory store keeps `useLocalStorageState` working the same as it does
// against a real browser, and never leaks into the next test.
beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers();
  const stored = new Map<string, string>();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: {
      get length() {
        return stored.size;
      },
      key: (index: number) => Array.from(stored.keys())[index] ?? null,
      getItem: (key: string) => stored.get(key) ?? null,
      setItem: (key: string, value: string) => void stored.set(key, String(value)),
      removeItem: (key: string) => void stored.delete(key),
      clear: () => stored.clear()
    }
  });
  container = document.createElement("div");
  document.body.appendChild(container);
});

afterEach(() => {
  if (root) act(() => root?.unmount());
  root = undefined;
  container.remove();
  document.body.innerHTML = "";
  vi.useRealTimers();
});

/** Let queued promise callbacks and debounce timers drain. */
async function settle(ticks = 3) {
  for (let index = 0; index < ticks; index += 1) {
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
  }
}

async function mount() {
  await act(async () => {
    root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    root.render(
      <QueryClientProvider client={client}>
        <PlayerSearchCombobox placeholder="nav.search.placeholder" />
      </QueryClientProvider>
    );
  });
  // Flushes useLocalStorageState's deferred `setTimeout(..., 0)` load.
  await settle();
  return container;
}

function inputEl(): HTMLInputElement {
  const node = document.body.querySelector<HTMLInputElement>('input[role="combobox"]');
  if (!node) throw new Error("no search input rendered");
  return node;
}

async function typeQuery(value: string) {
  const el = inputEl();
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
    setter?.call(el, value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** Opens the popover (`isOpen`) without changing the query, so an empty-query
 *  "Recent" group has a chance to mount. */
async function focusInput() {
  await act(async () => {
    inputEl().focus();
  });
}

/** Resolves the mocked search, advances the debounce, and lets the fetch
 *  effect's promise settle. */
async function search(query: string, users: MinimizedUser[]) {
  searchUsers.mockResolvedValueOnce(users);
  await typeQuery(query);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(300);
  });
  await settle();
}

function optionItems(): HTMLElement[] {
  return [...document.body.querySelectorAll<HTMLElement>('[role="option"]')];
}

function findItem(text: string): HTMLElement {
  const item = optionItems().find((el) => (el.textContent ?? "").trim().includes(text));
  if (!item) throw new Error(`no option matching "${text}"`);
  return item;
}

async function selectItem(el: HTMLElement) {
  await act(async () => {
    el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function readHistory(): Array<{ id: number; name: string }> {
  const raw = window.localStorage.getItem(HISTORY_KEY);
  return raw ? JSON.parse(raw) : [];
}

describe("PlayerSearchCombobox recent-search history", () => {
  it("selecting a result adds it to history", async () => {
    await mount();
    await search("ali", [user()]);

    await selectItem(findItem("Alice"));

    expect(readHistory()).toEqual([{ id: 1, name: "Alice" }]);
    expect(routerPush).toHaveBeenCalledTimes(1);
  });

  it("renders history when the input is empty", async () => {
    window.localStorage.setItem(HISTORY_KEY, JSON.stringify([{ id: 1, name: "Alice" }]));
    await mount();

    await focusInput();

    expect(document.body.textContent).toContain("nav.search.recent");
    expect(findItem("Alice")).toBeTruthy();
  });

  it("selecting the same player twice does not duplicate it", async () => {
    await mount();
    searchUsers.mockResolvedValue([user()]);

    await search("ali", [user()]);
    await selectItem(findItem("Alice"));
    expect(readHistory()).toEqual([{ id: 1, name: "Alice" }]);

    // Lets the debounce settle back to "" (cleared on select) before the
    // second search, so it actually re-fires for the repeated "ali" query
    // instead of bailing out on an unchanged debounced value.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300);
    });
    await search("ali", [user()]);
    await selectItem(findItem("Alice"));

    expect(readHistory()).toEqual([{ id: 1, name: "Alice" }]);
  });
});
