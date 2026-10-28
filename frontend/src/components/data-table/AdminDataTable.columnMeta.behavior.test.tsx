// @vitest-environment happy-dom
//
// The antd-like column meta on the admin table. What is pinned here:
//  1. `sticky: "right"` pins a right-edge suffix, offsets summed from declared
//     sizes, and the actions column joins it at the very edge;
//  2. `ellipsis: false` wraps instead of truncating; `true` truncates and
//     puts the value in a `title`;
//  3. `valign` overrides the table's `cellAlign` for its column only;
//  4. `onCell` lands its className and title on the `<td>`;
//  5. `headerTooltip` puts an info icon beside the sort button, not in it, so
//     reaching for the hint does not sort.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataTable } from "@/components/data-table/DataTable";
import { columnMeta, type AdminColumnMeta } from "@/components/data-table/columns";

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

const column = (id: keyof Row, meta: AdminColumnMeta<Row> = {}, size?: number): ColumnDef<Row> => ({
  accessorKey: id,
  header: id,
  size,
  meta: columnMeta<Row>(meta)
});

const actions: ColumnDef<Row> = {
  id: "actions",
  header: () => <span className="sr-only">Actions</span>,
  size: 96,
  cell: () => <button type="button">⋯</button>
};

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
        <DataTable<Row> rows={rows} columns={columns} />
      </QueryClientProvider>
    );
  });
}

/** `right` of every right-pinned cell matching `selector`, in column order. */
function rightOffsets(selector: "th" | "td"): string[] {
  return [...container.querySelectorAll<HTMLElement>(`${selector}[data-sticky="right"]`)].map(
    (cell) => cell.style.right
  );
}

/** The body cell whose text is exactly `text`. */
function bodyCell(text: string): HTMLElement {
  return [...container.querySelectorAll<HTMLElement>("tbody td")].find((cell) => cell.textContent === text)!;
}

function headerCell(text: string): HTMLElement {
  return [...container.querySelectorAll<HTMLElement>("thead th")].find((cell) => cell.textContent === text)!;
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("DataTable column meta", () => {
  it("pins a right-edge suffix, the actions column at the very edge", async () => {
    await render([
      column("name"),
      column("team", { sticky: "right" }, 120),
      column("note", { sticky: "right" }, 100),
      actions
    ]);

    expect(rightOffsets("th")).toEqual(["196px", "96px", "0px"]);
    expect(rightOffsets("td")).toEqual(["196px", "96px", "0px"]);
    expect(headerCell("name").hasAttribute("data-sticky")).toBe(false);
    // The edge shadow marks the innermost pinned column only.
    const edges = [...container.querySelectorAll('thead th[data-sticky="right"][data-sticky-edge]')];
    expect(edges).toHaveLength(1);
    expect(edges[0]?.textContent).toBe("team");
  });

  it("leaves the actions column unpinned when nothing pins right", async () => {
    await render([column("name"), column("team"), actions]);

    expect(container.querySelectorAll('[data-sticky="right"]')).toHaveLength(0);
  });

  it("wraps with `ellipsis: false` and titles with `ellipsis: true`", async () => {
    await render([column("name", { ellipsis: false }), column("team", { ellipsis: true }), column("note")]);

    const wrapped = bodyCell("Oblom");
    expect(wrapped.querySelector(".truncate")).toBeNull();
    expect(wrapped.querySelector(".whitespace-normal")).not.toBeNull();

    const titled = bodyCell("Blue").querySelector(".truncate");
    expect(titled?.getAttribute("title")).toBe("Blue");

    // Unset keeps truncating, without a title.
    const plain = bodyCell("—").querySelector(".truncate");
    expect(plain).not.toBeNull();
    expect(plain?.hasAttribute("title")).toBe(false);
  });

  it("applies `valign` to its own column only", async () => {
    await render([column("name", { valign: "top" }), column("team")]);

    expect(bodyCell("Oblom").classList.contains("align-top")).toBe(true);
    expect(bodyCell("Blue").classList.contains("align-top")).toBe(false);
    expect(bodyCell("Blue").classList.contains("align-middle")).toBe(true);
  });

  it("puts `onCell` className and title on the cell", async () => {
    await render([
      column("name", { onCell: (row) => ({ className: "text-destructive", title: `Player ${row.id}` }) }),
      column("team")
    ]);

    const cell = bodyCell("Oblom");
    expect(cell.classList.contains("text-destructive")).toBe(true);
    expect(cell.getAttribute("title")).toBe("Player 1");
    expect(bodyCell("Blue").hasAttribute("title")).toBe(false);
  });

  it("renders `headerTooltip` outside the sort button", async () => {
    await render([column("name", { headerTooltip: "Battle tag" }), column("team")]);

    const header = headerCell("name");
    const sortButton = header.querySelector("button")!;
    const icons = [...header.querySelectorAll("svg")].filter((icon) => !sortButton.contains(icon));
    expect(icons).toHaveLength(1);
    expect(icons[0]?.getAttribute("aria-hidden")).toBe("true");

    await act(async () => {
      icons[0]?.parentElement?.click();
    });
    expect(header.getAttribute("aria-sort")).toBe("none");

    await act(async () => {
      sortButton.click();
    });
    expect(header.getAttribute("aria-sort")).toBe("ascending");
  });
});
