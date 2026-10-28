// @vitest-environment happy-dom
//
// The table toolbar at both widths. Pinned here:
//  - commands: on a wide table they are buttons with the primary last and a
//    disabled one says why in visible text; on a narrow one the secondary ones
//    fold into the "View" menu and the primary keeps only its icon;
//  - a narrow table's filter picker shrinks beside the search with the active
//    count, and the chips get a row only while one is active;
//  - the "View" menu's second levels: a saved view survives the menu closing
//    for its dialog and restores the URL (with a null-state popstate, or Next's
//    router would treat it as a navigation) and the column visibility it was
//    saved with; deleting one applies nothing; a column toggle keeps the menu
//    on the columns level; the sort level (cards' only way to sort) keeps
//    the direction across a column change and the column across a direction
//    change, staying open between the two.
import { NextIntlClientProvider } from "next-intl";
import { Plus } from "lucide-react";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AdminTableToolbar,
  type AdminTableToolbarProps,
  type PickerColumn
} from "@/components/data-table/AdminTableToolbar";
import type { TableCommand } from "@/components/data-table/types";
import { FilterBar } from "@/components/kit/FilterBar";
import type { FilterDef, FilterState } from "@/components/kit/useFilters";
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

function item(role: "menuitem" | "menuitemcheckbox" | "menuitemradio", label: string): Element {
  const node = [...document.querySelectorAll(`[role='${role}']`)].find((candidate) =>
    (candidate.textContent ?? "").trim().startsWith(label)
  );
  if (!node) throw new Error(`no ${role} "${label}"`);
  return node;
}

/** Text when wide, `aria-label` when narrow. */
function viewTrigger(): Element {
  const node = [...container.querySelectorAll("button")].find(
    (candidate) => candidate.getAttribute("aria-label") === "View" || candidate.textContent?.trim() === "View"
  );
  if (!node) throw new Error("no View trigger");
  return node;
}

function buttonWithText(text: string): HTMLButtonElement | undefined {
  return [...container.querySelectorAll("button")].find((node) => node.textContent?.includes(text));
}

const pickerColumns: PickerColumn[] = [
  { id: "name", label: "Name", category: "core", defaultVisible: true, mandatory: true },
  { id: "stage", label: "Stage", category: "meta", defaultVisible: true, mandatory: false }
];
const visibility = { stage: false };
const onToggleColumn = vi.fn();
const onVisibilityChange = vi.fn();

async function render(props: Partial<AdminTableToolbarProps> = {}) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <NextIntlClientProvider locale="en" messages={en}>
        <AdminTableToolbar
          narrow={false}
          showSearch
          searchInputId="search"
          searchLabel="Search"
          searchValue=""
          onSearchChange={() => {}}
          isRefreshing={false}
          commands={[]}
          view={{
            selectedCount: 0,
            onExportCsv: () => {},
            canExport: true,
            density: "comfortable",
            onToggleDensity: () => {},
            prefsKey: "t",
            visibility,
            onVisibilityChange,
            pickerColumns,
            onToggleColumn,
            onResetColumns: () => {}
          }}
          {...props}
        />
      </NextIntlClientProvider>
    );
  });
}

// Node 22's own `localStorage` is unusable without `--localstorage-file`, and
// happy-dom does not shadow it: a per-test in-memory store stands in.
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
  onToggleColumn.mockClear();
  onVisibilityChange.mockClear();
  window.history.replaceState(null, "", "/admin/x?status=pending");
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("AdminTableToolbar commands", () => {
  it("puts the primary last on a wide table and says why a disabled one waits", async () => {
    const commands: TableCommand[] = [
      { id: "create", label: "Create team", icon: Plus, primary: true, disabledReason: "Pick a tournament first" },
      { id: "sync", label: "Sync teams", onSelect: () => {} }
    ];
    await render({ commands });

    const labels = [...container.querySelectorAll("button")].map((node) => node.textContent?.trim()).filter(Boolean);
    expect(labels.slice(-2)).toEqual(["Sync teams", "Create team"]);
    const create = buttonWithText("Create team")!;
    expect(create.disabled).toBe(true);
    expect(document.getElementById(create.getAttribute("aria-describedby") ?? "")?.textContent).toBe(
      "Pick a tournament first"
    );
  });

  it("folds the secondary commands into the View menu on a narrow table and keeps the primary's icon", async () => {
    const sync = vi.fn();
    const commands: TableCommand[] = [
      { id: "sync", label: "Sync catalog", onSelect: sync },
      { id: "create", label: "Create hero", icon: Plus, primary: true, onSelect: () => {} }
    ];
    await render({ narrow: true, commands });

    expect(buttonWithText("Sync catalog")).toBeUndefined();
    expect(container.querySelector("button[aria-label='Create hero']")?.textContent).toBe("");

    await open(viewTrigger());
    await click(item("menuitem", "Sync catalog"));
    expect(sync).toHaveBeenCalledTimes(1);
  });
});

describe("AdminTableToolbar filters on a narrow table", () => {
  const defs: FilterDef[] = [
    {
      key: "status",
      label: "Status",
      kind: "single",
      options: [
        { value: "pending", label: "Pending" },
        { value: "approved", label: "Approved" }
      ]
    }
  ];
  const state = (status: string): FilterState => ({
    values: { status },
    set: vi.fn(),
    setMany: vi.fn(),
    clear: vi.fn(),
    toTableFilters: () => ({}),
    filterKey: status
  });

  it("shrinks the picker to an icon and leaves the chips out while none is active", async () => {
    await render({ narrow: true, filters: <FilterBar defs={defs} filters={state("")} /> });

    expect(container.querySelector("[aria-label='Add filter']")?.textContent).toBe("");
    expect(container.querySelector("[aria-label='Active filters']")).toBeNull();
  });

  it("counts the active filters on the picker and lists their chips", async () => {
    await render({ narrow: true, filters: <FilterBar defs={defs} filters={state("pending")} /> });

    expect(container.querySelector("[aria-label='Add filter']")?.textContent).toBe("1");
    expect(container.querySelector("[aria-label='Active filters']")?.textContent).toContain("Status: Pending");
  });
});

describe("AdminTableToolbar View menu", () => {
  it("saves a view though the menu closes for its dialog, and restores its URL and columns", async () => {
    await render();
    await open(viewTrigger());
    await click(item("menuitem", "Views"));
    await click(item("menuitem", "Save current view"));

    expect(document.querySelector("[role='menu']")).toBeNull();
    const input = document.getElementById("admin-saved-view-name") as HTMLInputElement | null;
    expect(input).not.toBeNull();
    await act(async () => {
      const setValue = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!;
      setValue.call(input, "Pending");
      input!.dispatchEvent(new Event("input", { bubbles: true }));
    });
    await act(async () => {
      input!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      await tick();
    });
    expect(JSON.parse(localStorage.getItem("t:views") ?? "[]")).toEqual([
      { name: "Pending", search: "?status=pending", extra: visibility }
    ]);

    // The reader moves on from the filtered state, then comes back through the view.
    window.history.replaceState(null, "", "/admin/x");
    const popstate = vi.fn();
    window.addEventListener("popstate", popstate);
    await open(viewTrigger());
    await click(item("menuitem", "Views"));
    await click(item("menuitem", "Pending"));
    window.removeEventListener("popstate", popstate);

    expect(window.location.search).toBe("?status=pending");
    expect(popstate).toHaveBeenCalledTimes(1);
    expect((popstate.mock.calls[0][0] as PopStateEvent).state).toBeNull();
    expect(onVisibilityChange).toHaveBeenCalledWith(visibility);
  });

  it("deletes a view without applying it", async () => {
    localStorage.setItem("t:views", JSON.stringify([{ name: "Pending", search: "?status=pending", extra: visibility }]));
    await render();
    await open(viewTrigger());
    await click(item("menuitem", "Views"));
    await click(document.querySelector("[aria-label='Delete view Pending']")!);

    expect(JSON.parse(localStorage.getItem("t:views") ?? "[]")).toEqual([]);
    expect(onVisibilityChange).not.toHaveBeenCalled();
    expect(window.location.search).toBe("?status=pending");
  });

  it("toggles a column without leaving the columns level", async () => {
    await render({ narrow: true });
    await open(viewTrigger());
    await click(item("menuitem", "Columns"));
    await click(item("menuitemcheckbox", "Stage"));

    expect(onToggleColumn).toHaveBeenCalledWith("stage");
    expect(item("menuitemcheckbox", "Stage")).toBeTruthy();
    expect(item("menuitemcheckbox", "Name").getAttribute("aria-disabled")).toBe("true");
  });

  it("sorts from the sort level, keeping the other half of the sort", async () => {
    const onChange = vi.fn();
    const columns = [
      { id: "name", label: "Name" },
      { id: "stage", label: "Stage" }
    ];
    await render({
      narrow: true,
      view: {
        selectedCount: 0,
        onExportCsv: () => {},
        canExport: true,
        onToggleDensity: () => {},
        prefsKey: "t",
        visibility,
        onVisibilityChange,
        onToggleColumn,
        onResetColumns: () => {},
        sort: { columns, value: { id: "name", desc: true }, onChange }
      }
    });
    await open(viewTrigger());
    await click(item("menuitem", "Sort"));
    await click(item("menuitemradio", "Stage"));
    expect(onChange).toHaveBeenLastCalledWith({ id: "stage", desc: true });

    await click(item("menuitemradio", "Ascending"));
    expect(onChange).toHaveBeenLastCalledWith({ id: "name", desc: false });
  });
});
