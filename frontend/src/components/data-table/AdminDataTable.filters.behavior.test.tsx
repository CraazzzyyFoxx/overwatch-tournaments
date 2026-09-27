// @vitest-environment happy-dom
//
// Column-declared filters on the admin table. The header no longer has a
// filter control of its own — `kit/FilterBar` owns that surface — so what
// is pinned here is the engine underneath it:
//  1. the header holds sorting only, and no filter popover;
//  2. a filter handed in refetches with that value and writes it to the URL
//     under the endpoint's own param name;
//  3. a filter change resets to page 1 — narrowing while on page 4 otherwise
//     lands on a page the new result set does not have;
//  4. back/forward restores the filter from the URL;
//  5. a deep link's filter survives the load, controlled or not — state set
//     from the URL lands a render later (and a controlled parent applies it a
//     render after that), and the URL writer used to overwrite the link with
//     that stale, empty filter set.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act, StrictMode, useEffect, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DataTable } from "@/components/data-table/DataTable";
import { columnMeta } from "@/components/data-table/columns";
import type { AdminTableFilters } from "@/components/data-table/filters";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/encounters"
}));

interface Row {
  id: number;
  status: string;
}

const columns: ColumnDef<Row>[] = [
  {
    accessorKey: "status",
    header: "Status",
    meta: columnMeta<Row>({
      filter: {
        param: "status",
        label: "Filter by status",
        options: [
          { value: "OPEN", label: "Open" },
          { value: "PENDING", label: "Pending" }
        ]
      }
    })
  }
];

const queryFn = vi.fn();
let container: HTMLElement;
let root: Root;
/** Set by `renderControlled`; pushes a filter the way a chip would. */
let applyFilters: (next: AdminTableFilters) => void = () => {};

function lastCallFilters(): AdminTableFilters {
  const call = queryFn.mock.calls.at(-1);
  return (call?.[5] ?? {}) as AdminTableFilters;
}

function lastCallPage(): number {
  return queryFn.mock.calls.at(-1)?.[0] as number;
}

async function click(element: Element | null | undefined) {
  await act(async () => {
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

async function render(search = "") {
  window.history.replaceState(null, "", `/admin/encounters${search}`);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <DataTable<Row>
          queryKey={(page, searchValue, pageSize, sortField, sortDir, filters) => [
            "rows",
            page,
            searchValue,
            pageSize,
            sortField,
            sortDir,
            filters
          ]}
          queryFn={queryFn}
          columns={columns}
        />
      </QueryClientProvider>
    );
  });
}

/**
 * The table with its filters owned from outside, which is how a screen wires
 * `kit/FilterBar` to it: the chips write the URL, this reads it back.
 * `applyFilters` stands in for a chip being picked.
 */
async function renderControlled(search = "") {
  window.history.replaceState(null, "", `/admin/encounters${search}`);
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });

  function Harness() {
    const [filters, setFilters] = useState<AdminTableFilters>({});
    // Published from an effect, not during render: writing a module-scope binding
    // while rendering is a side effect the react-compiler rules reject.
    useEffect(() => {
      applyFilters = setFilters;
    }, [setFilters]);
    return (
      <DataTable<Row>
        filters={filters}
        onFiltersChange={setFilters}
        queryKey={(page, searchValue, pageSize, sortField, sortDir, tableFilters) => [
          "rows",
          page,
          searchValue,
          pageSize,
          sortField,
          sortDir,
          tableFilters
        ]}
        queryFn={queryFn}
        columns={columns}
      />
    );
  }

  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <Harness />
      </QueryClientProvider>
    );
  });
}

beforeEach(() => {
  queryFn.mockReset();
  queryFn.mockResolvedValue({
    results: [{ id: 1, status: "OPEN" }],
    total: 100,
    page: 1,
    per_page: 15
  });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
});

describe("DataTable column filters", () => {
  it("puts nothing but sorting in the header", async () => {
    await render();
    // The funnel popover is gone: one filter surface per screen, and it is the
    // filter bar above the table.
    expect(container.querySelector('th button[aria-label^="Filter by"]')).toBeNull();

    const sortButton = [...container.querySelectorAll("th button")].find((node) =>
      node.textContent?.includes("Status")
    );
    expect(sortButton).toBeDefined();
  });

  it("centres body cells, so a one-line cell beside a two-line one does not float", async () => {
    await render();
    const cell = container.querySelector("tbody td");

    expect(cell?.className).toContain("align-middle");
    expect(cell?.className).not.toContain("align-top");
  });

  it("refetches with the value the caller sets and puts it in the URL", async () => {
    await renderControlled();
    await act(async () => {
      applyFilters({ status: ["OPEN"] });
    });

    expect(lastCallFilters()).toEqual({ status: ["OPEN"] });
    expect(new URLSearchParams(window.location.search).get("status")).toBe("OPEN");
  });

  it("resets to page 1 when a filter changes", async () => {
    await renderControlled("?page=4");
    expect(lastCallPage()).toBe(4);

    await act(async () => {
      applyFilters({ status: ["PENDING"] });
    });

    expect(lastCallPage()).toBe(1);
    expect(new URLSearchParams(window.location.search).get("page")).toBeNull();
  });

  it("restores the filter from the URL on back/forward", async () => {
    await render();
    window.history.replaceState(null, "", "/admin/encounters?status=PENDING");
    await act(async () => {
      window.dispatchEvent(new PopStateEvent("popstate"));
    });

    expect(lastCallFilters()).toEqual({ status: ["PENDING"] });
  });

  it("grows the list one batch at a time when paging is infinite", async () => {
    queryFn.mockClear();
    const rows = Array.from({ length: 7 }, (_unused, index) => ({
      id: index + 1,
      status: index % 2 === 0 ? "OPEN" : "PENDING"
    }));
    window.history.replaceState(null, "", "/admin/encounters");
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <DataTable<Row>
            rows={rows}
            columns={columns}
            getRowId={(row) => String(row.id)}
            initialPageSize={3}
            paging="infinite"
            rowUnit="encounters"
          />
        </QueryClientProvider>
      );
    });

    expect(container.querySelectorAll("tbody tr[data-row-id]").length).toBe(3);
    expect(container.textContent).toContain("Showing 3 of 7 encounters");
    // No page numbers compete with the sentinel.
    expect(container.querySelector("button[aria-label='Next page']")).toBeNull();

    const loadMore = [...container.querySelectorAll("button")].find((node) =>
      node.textContent?.includes("Load more encounters")
    );
    await click(loadMore);
    expect(container.querySelectorAll("tbody tr[data-row-id]").length).toBe(6);

    await click(loadMore);
    expect(container.querySelectorAll("tbody tr[data-row-id]").length).toBe(7);
    // Everything loaded: the button retires, the count stays.
    expect(container.textContent).toContain("Showing 7 of 7 encounters");
    expect(
      [...container.querySelectorAll("button")].some((node) =>
        node.textContent?.includes("Load more")
      )
    ).toBe(false);
  });

  it("renders every row with no pager when paging is all", async () => {
    queryFn.mockClear();
    const rows = Array.from({ length: 7 }, (_unused, index) => ({
      id: index + 1,
      status: index % 2 === 0 ? "OPEN" : "PENDING"
    }));
    window.history.replaceState(null, "", "/admin/encounters");
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await act(async () => {
      root.render(
        <QueryClientProvider client={client}>
          <DataTable<Row>
            rows={rows}
            columns={columns}
            getRowId={(row) => String(row.id)}
            initialPageSize={3}
            paging="all"
          />
        </QueryClientProvider>
      );
    });

    expect(container.querySelectorAll("tbody tr[data-row-id]").length).toBe(7);
    expect(container.querySelector("button[aria-label='Next page']")).toBeNull();
    expect(
      [...container.querySelectorAll("button")].some((node) =>
        node.textContent?.includes("Load more")
      )
    ).toBe(false);
  });

  it("ignores a value the column does not declare", async () => {
    await render("?status=NONSENSE");
    expect(lastCallFilters()).toEqual({});
  });

  it("keeps a deep link's filter through the load when the caller owns it", async () => {
    function Controlled() {
      const [filters, setFilters] = useState<AdminTableFilters>({});
      return (
        <DataTable<Row>
          filters={filters}
          onFiltersChange={setFilters}
          queryKey={(page, searchValue, pageSize, sortField, sortDir, tableFilters) => [
            "rows",
            page,
            searchValue,
            pageSize,
            sortField,
            sortDir,
            tableFilters
          ]}
          queryFn={queryFn}
          columns={columns}
        />
      );
    }

    window.history.replaceState(null, "", "/admin/encounters?status=OPEN");
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await act(async () => {
      root.render(
        <StrictMode>
          <QueryClientProvider client={client}>
            <Controlled />
          </QueryClientProvider>
        </StrictMode>
      );
    });
    for (let turn = 0; turn < 5; turn += 1) {
      await act(async () => {
        const { promise, resolve } = Promise.withResolvers<void>();
        setTimeout(resolve, 0);
        await promise;
      });
    }

    expect(new URLSearchParams(window.location.search).get("status")).toBe("OPEN");
    expect(lastCallFilters()).toEqual({ status: ["OPEN"] });
  });
});
