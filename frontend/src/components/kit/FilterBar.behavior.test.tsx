// @vitest-environment happy-dom
//
// The one filter surface for the admin panel. What is pinned here:
//  1. applying a chip writes the URL — a filter that lives in component state
//     dies on reload and cannot be pasted into Discord, which is the whole
//     reason chips replaced the old `<Select>`;
//  2. a reload restores the chip from the URL;
//  3. `clear` drops every filter AND `page`, so narrowing does not strand the
//     user on a page the new result set no longer has;
//  4. a pinned chip has no remove control (the tournament inside a hub);
//  5. a preset applies all its keys in ONE write — sequential `set` calls read
//     the same stale query snapshot and only the last one would survive.
import { act, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { FilterBar } from "@/components/kit/FilterBar";
import { useFilters, type FilterDef } from "@/components/kit/useFilters";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const replace = vi.fn((url: string) => {
  window.history.replaceState(null, "", url);
  currentSearch = new URL(url, "http://localhost").search;
  rerender?.();
});

let currentSearch = "";
let rerender: (() => void) | null = null;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/matches",
  useRouter: () => ({ replace, push: replace }),
  useSearchParams: () => new URLSearchParams(currentSearch)
}));

const DEFS: FilterDef[] = [
  {
    key: "status",
    label: "Status",
    kind: "single",
    options: [
      { value: "pending", label: "Pending", count: 4 },
      { value: "disputed", label: "Disputed" }
    ]
  },
  { key: "has_logs", label: "Has logs", kind: "toggle" }
];

let container: HTMLElement;
let root: Root;

function Harness() {
  const [, force] = useState(0);
  // Published from an effect, not during render: writing a module-scope binding
  // while rendering is a side effect the react-compiler rules reject.
  useEffect(() => {
    rerender = () => force((value) => value + 1);
  }, []);
  const filters = useFilters(DEFS);
  return (
    <FilterBar
      defs={DEFS}
      filters={filters}
      pinned={[{ key: "tournament", label: "Tournament: Anak Cup #14" }]}
      presets={[{ label: "Needs attention", values: { status: "disputed", has_logs: true } }]}
    />
  );
}

async function render(search = "") {
  currentSearch = search;
  window.history.replaceState(null, "", `/admin/matches${search}`);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<Harness />);
  });
}

async function click(element: Element | null | undefined) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function chip(label: string) {
  return container.querySelector<HTMLButtonElement>(
    `button[aria-label="Remove filter ${label}"]`
  );
}

function commandItem(label: string) {
  return [...document.querySelectorAll('[cmdk-item=""]')].find(
    (item) => item.textContent?.trim().startsWith(label)
  );
}

beforeEach(() => {
  replace.mockClear();
  rerender = null;
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("FilterBar", () => {
  it("writes a picked filter into the URL", async () => {
    await render();

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(commandItem("Status"));
    await click(commandItem("Pending"));

    expect(replace).toHaveBeenCalled();
    expect(new URL(replace.mock.calls.at(-1)![0], "http://x").searchParams.get("status")).toBe(
      "pending"
    );
  });

  it("restores an active chip from the URL on load", async () => {
    await render("?status=disputed");

    expect(chip("Status: Disputed")).not.toBeNull();
  });

  it("sets a toggle chip straight from the filter list", async () => {
    await render();

    await click(container.querySelector('button[aria-label="Add filter"]'));
    await click(commandItem("Has logs"));

    expect(new URL(replace.mock.calls.at(-1)![0], "http://x").searchParams.get("has_logs")).toBe(
      "1"
    );
  });

  it("removes a filter when its chip is clicked", async () => {
    await render("?status=pending");

    await click(chip("Status: Pending"));

    const url = new URL(replace.mock.calls.at(-1)![0], "http://x");
    expect(url.searchParams.get("status")).toBeNull();
  });

  it("clears every filter and the page cursor at once", async () => {
    await render("?status=pending&has_logs=1&page=4");

    await click(
      [...container.querySelectorAll("button")].find(
        (button) => button.textContent?.trim() === "Clear all"
      )
    );

    const url = new URL(replace.mock.calls.at(-1)![0], "http://x");
    expect(url.searchParams.get("status")).toBeNull();
    expect(url.searchParams.get("has_logs")).toBeNull();
    expect(url.searchParams.get("page")).toBeNull();
  });

  it("renders a pinned chip with no remove control", async () => {
    await render();

    const pinnedChip = container.querySelector('[data-pinned-filter="tournament"]');
    expect(pinnedChip?.textContent).toContain("Anak Cup #14");
    expect(pinnedChip?.tagName).toBe("SPAN");
    expect(chip("Tournament: Anak Cup #14")).toBeNull();
  });

  it("applies a preset in a single URL write", async () => {
    await render();

    await click(
      [...container.querySelectorAll("button")].find(
        (button) => button.textContent?.trim() === "Needs attention"
      )
    );

    expect(replace).toHaveBeenCalledTimes(1);
    const url = new URL(replace.mock.calls.at(-1)![0], "http://x");
    expect(url.searchParams.get("status")).toBe("disputed");
    expect(url.searchParams.get("has_logs")).toBe("1");
  });
});
