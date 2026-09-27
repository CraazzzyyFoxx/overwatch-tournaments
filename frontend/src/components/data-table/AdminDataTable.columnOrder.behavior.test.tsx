// @vitest-environment happy-dom
//
// A saved column order is a preference over the columns that existed when it
// was written. A column that appears later (conditional on a setting, or a
// custom field arriving from a query) must slot in before the actions column,
// not after it — that is what put the ⋯ menu in the middle of the row.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DataTable } from "@/components/data-table/DataTable";
import { createKebabColumn } from "@/components/data-table/kebab-column";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/players"
}));

interface Row {
  id: number;
  name: string;
  team: string;
  subscription: string;
}

const ROWS: Row[] = [{ id: 1, name: "Ana", team: "Blue", subscription: "active" }];

const base: ColumnDef<Row>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "team", header: "Team" }
];
const subscription: ColumnDef<Row> = { accessorKey: "subscription", header: "Subscription" };
const actions = createKebabColumn<Row>(() => [{ label: "Edit", onSelect: () => undefined }]);

let container: HTMLElement;
let root: Root;

async function render(columns: ColumnDef<Row>[]) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <DataTable<Row> rows={ROWS} columns={columns} columnsStorageKey="players" />
      </QueryClientProvider>
    );
  });
  // `useLocalStorageState` reads the store a tick after mount.
  await act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });
}

// The filler column that soaks up leftover width is `aria-hidden` and not a column of the data.
const headerTexts = () => [...container.querySelectorAll("thead th:not([aria-hidden])")].map((th) => th.textContent?.trim());
const cellTexts = () => [...container.querySelectorAll("tbody tr[data-row-id] td:not([aria-hidden])")].map((td) => td.textContent?.trim());

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
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("DataTable column order", () => {
  it("keeps the actions column last when a column appears after the order was saved", async () => {
    // Saved while only Name/Team existed, with Team dragged in front — and with
    // the actions id inside, the way the first version of the feature wrote it.
    localStorage.setItem("players:order", JSON.stringify(["team", "name", "actions"]));
    await render([...base, subscription, actions]);

    expect(headerTexts()).toEqual(["Team", "Name", "Subscription", "Actions"]);
    expect(cellTexts().slice(0, 3)).toEqual(["Blue", "Ana", "active"]);
  });

  it("ignores saved ids for columns that no longer exist", async () => {
    localStorage.setItem("players:order", JSON.stringify(["subscription", "team", "name"]));
    await render([...base, actions]);

    expect(headerTexts()).toEqual(["Team", "Name", "Actions"]);
  });
});

describe("DataTable actions column width", () => {
  it("ignores a saved sizing for the actions column and offers no resize handle on it", async () => {
    localStorage.setItem("players:sizing", JSON.stringify({ actions: 339, name: 200 }));
    await render([...base, actions]);

    const heads = [...container.querySelectorAll<HTMLElement>("thead th:not([aria-hidden])")];
    const actionsHead = heads.find((th) => th.textContent?.trim() === "Actions")!;
    expect(actionsHead.style.maxWidth).toBe("80px");
    expect(actionsHead.querySelector("[role='separator']")).toBeNull();
    // Other columns keep their saved width and their handle.
    const nameHead = heads.find((th) => th.textContent?.trim().startsWith("Name"))!;
    expect(nameHead.style.width).toBe("200px");
    expect(nameHead.querySelector("[role='separator']")).not.toBeNull();
  });
});
