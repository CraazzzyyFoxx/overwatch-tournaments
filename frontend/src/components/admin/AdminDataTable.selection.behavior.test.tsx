// @vitest-environment happy-dom
//
// Selection and sorting contracts that reach past the current page:
//  1. server mode — a row selected on page 1 is still handed to `bulkActions`
//     after paging to page 2, and the toolbar says how many are off-page;
//  2. client mode — Shift+click on a second header stacks the sort and the URL
//     carries both columns, restoring them on a reload.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminDataTable } from "@/components/admin/AdminDataTable";

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
}

const ROWS: Row[] = [
  { id: 1, name: "Ana", team: "Blue" },
  { id: 2, name: "Bob", team: "Red" },
  { id: 3, name: "Cid", team: "Blue" },
  { id: 4, name: "Dee", team: "Red" }
];

const columns: ColumnDef<Row>[] = [
  { accessorKey: "name", header: "Name" },
  { accessorKey: "team", header: "Team" }
];

let container: HTMLElement;
let root: Root;
const bulkActions = vi.fn((selected: Row[]) => <span>{`bulk:${selected.map((row) => row.id).join(",")}`}</span>);

async function render(props: Partial<React.ComponentProps<typeof AdminDataTable<Row>>>) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <AdminDataTable<Row> columns={columns} getRowId={(row) => String(row.id)} initialPageSize={2} {...props} />
      </QueryClientProvider>
    );
  });
  await flush();
}

async function click(element: Element | null | undefined, init: MouseEventInit = {}) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true, ...init }));
  });
}

/** Lets a resolved query land in the tree. */
const flush = () =>
  act(async () => {
    const { promise, resolve } = Promise.withResolvers<void>();
    setTimeout(resolve, 0);
    await promise;
  });

const button = (label: string) => container.querySelector(`button[aria-label="${label}"]`);
const headerButton = (text: string) =>
  [...container.querySelectorAll("thead button")].find((node) => node.textContent?.trim().startsWith(text));

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
  window.history.replaceState(null, "", "/admin/players");
});

describe("AdminDataTable selection across pages", () => {
  it("keeps a row selected on an earlier page in the bulk action payload", async () => {
    await render({
      queryKey: (page) => ["players", page],
      queryFn: async (page, _search, pageSize) => ({
        results: ROWS.slice((page - 1) * pageSize, page * pageSize),
        total: ROWS.length,
        page,
        per_page: pageSize
      }),
      enableRowSelection: () => true,
      bulkActions
    });

    await click(button("Select row 1"));
    expect(container.textContent).toContain("bulk:1");

    await click(button("Next page"));
    await flush();
    expect(button("Select row 3")).not.toBeNull();
    // Row 1 is no longer rendered but still selected, and still in the payload.
    expect(container.textContent).toContain("bulk:1");
    expect(container.textContent).toContain("1 on other pages");

    await click(button("Select row 3"));
    expect(container.textContent).toContain("bulk:1,3");
  });
});

describe("AdminDataTable multi-sort", () => {
  it("stacks a second sort with Shift+click and writes both to the URL", async () => {
    await render({ rows: ROWS, initialPageSize: 10 });

    await click(headerButton("Team"));
    await click(headerButton("Name"), { shiftKey: true });

    const names = [...container.querySelectorAll("tbody tr[data-row-id]")].map((tr) => tr.querySelector("td")?.textContent);
    expect(names).toEqual(["Ana", "Cid", "Bob", "Dee"]);
    expect(window.location.search).toBe("?sort=team%2Cname");
    // The second column shows its priority so the stacking is visible.
    expect(container.querySelector('[aria-label="Sort priority 2"]')?.textContent).toBe("2");
  });

  it("restores a stacked sort from the URL", async () => {
    window.history.replaceState(null, "", "/admin/players?sort=team%2Cname&dir=asc%2Cdesc");
    await render({ rows: ROWS, initialPageSize: 10 });

    const names = [...container.querySelectorAll("tbody tr[data-row-id]")].map((tr) => tr.querySelector("td")?.textContent);
    expect(names).toEqual(["Cid", "Ana", "Dee", "Bob"]);
  });
});
