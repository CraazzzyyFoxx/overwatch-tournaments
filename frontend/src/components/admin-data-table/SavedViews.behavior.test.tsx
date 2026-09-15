// @vitest-environment happy-dom
//
// A saved view is only useful if restoring it puts the table back where it was:
// the URL carries page/sort/filters/search, and `extra` carries whatever the
// URL cannot (column visibility). Both halves are pinned here, plus the
// popstate the table listens on — with a null state, or Next's router would
// treat it as a route transition.
import { NextIntlClientProvider } from "next-intl";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminSavedViews } from "./SavedViews";
import en from "@/i18n/messages/en.json";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let container: HTMLElement;
let root: Root;

function tick() {
  const { promise, resolve } = Promise.withResolvers<void>();
  setTimeout(resolve, 0);
  return promise;
}

/** Radix opens on `pointerdown`, so a bare click never reaches the menu. */
function open(node: Element) {
  return act(async () => {
    node.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function click(node: Element) {
  return act(async () => {
    node.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    await tick();
  });
}

function menuItem(label: string): Element {
  const node = [...document.querySelectorAll("[role='menuitem']")].find((candidate) =>
    (candidate.textContent ?? "").trim().startsWith(label)
  );
  if (!node) throw new Error(`no menu item "${label}"`);
  return node;
}

function trigger(): Element {
  const node = [...container.querySelectorAll("button")].find((candidate) =>
    (candidate.textContent ?? "").includes("Views")
  );
  if (!node) throw new Error("no Views trigger");
  return node;
}

const columns = { id: true, stage: false };
const apply = vi.fn();
const extra = { get: () => columns, apply };

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      // The save dialog's close button takes its label from next-intl.
      <NextIntlClientProvider locale="en" messages={en}>
        <AdminSavedViews storageKey="t" extra={extra} />
      </NextIntlClientProvider>
    );
  });
  await act(async () => {
    await tick();
  });
}

// Node 22 exposes its own `localStorage` that is unusable without
// `--localstorage-file`, and happy-dom does not shadow it. A per-test in-memory
// store behaves like a real browser's and never leaks into the next test.
beforeEach(() => {
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
  apply.mockClear();
  window.history.replaceState(null, "", "/admin/x?status=pending&sort=name");
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("AdminSavedViews", () => {
  it("offers only the save item until a view exists", async () => {
    await render();
    await open(trigger());

    expect(document.querySelectorAll("[role='menuitem']")).toHaveLength(1);
    expect(menuItem("Save current view").textContent).toContain("Save current view");
  });

  it("restores the URL, the popstate and the extra payload of a saved view", async () => {
    await render();
    await open(trigger());
    await click(menuItem("Save current view"));

    const input = document.querySelector<HTMLInputElement>("#admin-saved-view-name");
    expect(input).not.toBeNull();
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(
        input,
        "Pending"
      );
      input!.dispatchEvent(new Event("input", { bubbles: true }));
      await tick();
    });
    await act(async () => {
      input!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      await tick();
    });

    expect(JSON.parse(localStorage.getItem("t:views") ?? "[]")).toEqual([
      { name: "Pending", search: "?status=pending&sort=name", extra: columns }
    ]);

    // The user navigates away from the filtered state.
    window.history.replaceState(null, "", "/admin/x");
    const popstate = vi.fn();
    window.addEventListener("popstate", popstate);

    await open(trigger());
    await click(menuItem("Pending"));
    window.removeEventListener("popstate", popstate);

    expect(window.location.search).toBe("?status=pending&sort=name");
    expect(popstate).toHaveBeenCalledTimes(1);
    expect((popstate.mock.calls[0][0] as PopStateEvent).state).toBeNull();
    expect(apply).toHaveBeenCalledWith(columns);
  });

  it("deletes a view without applying it", async () => {
    localStorage.setItem(
      "t:views",
      JSON.stringify([{ name: "Pending", search: "?status=pending", extra: columns }])
    );
    await render();
    await open(trigger());
    await click(document.querySelector("[aria-label='Delete view Pending']")!);

    expect(JSON.parse(localStorage.getItem("t:views") ?? "[]")).toEqual([]);
    expect(apply).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?status=pending&sort=name");
  });
});
