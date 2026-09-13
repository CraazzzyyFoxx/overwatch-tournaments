// @vitest-environment happy-dom
//
// Sticky columns on the admin table. What is pinned here:
//  1. a column with `meta.sticky` gets the sticky class in both its header
//     and its body cells;
//  2. offsets stack from declared sizes, and the expand/select column is
//     pinned first so the pinned block has no gap;
//  3. `sticky` is only honoured on a left-edge prefix — a flagged column with
//     scrolling columns in front of it would park over the wrong neighbours;
//  4. the edge shadow marks the last pinned column, not every one.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminDataTable } from "@/components/admin/AdminDataTable";
import { adminColumnMeta } from "@/components/admin/admin-table-columns";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/registrations"
}));

interface Row {
  id: number;
  name: string;
  team: string;
  note: string;
}

const rows: Row[] = [{ id: 1, name: "Oblom", team: "Blue", note: "—" }];

const column = (id: keyof Row, sticky: boolean, size?: number): ColumnDef<Row> => ({
  accessorKey: id,
  header: id,
  size,
  meta: adminColumnMeta<Row>({ sticky })
});

let container: HTMLElement;
let root: Root;

async function render(columns: ColumnDef<Row>[], expandable = false) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <AdminDataTable<Row>
          rows={rows}
          columns={columns}
          renderExpanded={expandable ? () => <p>details</p> : undefined}
        />
      </QueryClientProvider>
    );
  });
}

/** `left` of every pinned cell in the header row, in column order. */
function headerOffsets(): (string | undefined)[] {
  return [...container.querySelectorAll<HTMLElement>("th.admin-sticky-col")].map(
    (cell) => cell.style.left
  );
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("AdminDataTable sticky columns", () => {
  it("pins the flagged column in the header and the body", async () => {
    await render([column("name", true), column("team", false)]);

    const headers = [...container.querySelectorAll("thead th")];
    expect(headers[0]?.classList.contains("admin-sticky-col")).toBe(true);
    expect(headers[1]?.classList.contains("admin-sticky-col")).toBe(false);

    const cells = [...container.querySelectorAll("tbody td")];
    expect(cells[0]?.classList.contains("admin-sticky-col")).toBe(true);
    expect(cells[1]?.classList.contains("admin-sticky-col")).toBe(false);
  });

  it("stacks offsets from declared sizes", async () => {
    await render([column("name", true, 240), column("team", true, 120), column("note", true)]);

    expect(headerOffsets()).toEqual(["0px", "240px", "360px"]);
  });

  it("pins the expand column ahead of the first data column", async () => {
    await render([column("name", true, 240), column("team", true)], true);

    // Leading cell at 0, then the 40px-wide `w-10` expander is accounted for.
    expect(headerOffsets()).toEqual(["0px", "40px", "280px"]);
    const leading = container.querySelector("tbody td");
    expect(leading?.classList.contains("admin-sticky-col")).toBe(true);
  });

  it("ignores sticky on a column that is not part of the left-edge prefix", async () => {
    await render([column("name", false), column("team", true)]);

    expect(container.querySelectorAll(".admin-sticky-col")).toHaveLength(0);
  });

  it("marks only the last pinned column with the edge shadow", async () => {
    await render([column("name", true, 240), column("team", true), column("note", false)]);

    const edges = [...container.querySelectorAll("thead th.admin-sticky-col-edge")];
    expect(edges).toHaveLength(1);
    expect(edges[0]?.textContent).toContain("team");
  });
});
