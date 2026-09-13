// @vitest-environment happy-dom
//
// Paint-selection in the admin table: press one checkbox and sweep across
// rows to give them the same state; shift-press extends from the last press.
// happy-dom has no layout, so `elementFromPoint` is stubbed to map a y
// coordinate onto a row — the hook's contract is "whatever row is under the
// pointer", which is exactly what the stub answers.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AdminDataTable } from "@/components/admin/AdminDataTable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/matches"
}));

interface Row {
  id: number;
  status: string;
}

const ROWS: Row[] = [1, 2, 3, 4].map((id) => ({ id, status: id === 3 ? "locked" : "pending" }));

const columns: ColumnDef<Row>[] = [
  { accessorKey: "id", header: "#" },
  { accessorKey: "status", header: "Status" }
];

let container: HTMLElement;
let root: Root;

async function render() {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <AdminDataTable<Row>
          rows={ROWS}
          columns={columns}
          getRowId={(row) => String(row.id)}
          enableRowSelection={(row) => row.original.status !== "locked"}
        />
      </QueryClientProvider>
    );
  });
  // Row N sits at y = N * 100.
  document.elementFromPoint = (_x, y) => container.querySelector(`tr[data-row-id="${y / 100}"]`);
}

const checkbox = (id: number) => container.querySelector<HTMLElement>(`button[aria-label="Select row ${id}"]`)!;
const selectedIds = () =>
  [...container.querySelectorAll('tbody tr[data-state="selected"]')].map((tr) => Number(tr.getAttribute("data-row-id")));

async function press(id: number, init: MouseEventInit = {}) {
  await act(async () => {
    checkbox(id).dispatchEvent(new MouseEvent("pointerdown", { bubbles: true, button: 0, clientX: 10, clientY: id * 100, ...init }));
  });
}
async function sweepTo(id: number) {
  await act(async () => {
    window.dispatchEvent(new MouseEvent("pointermove", { clientX: 10, clientY: id * 100 }));
  });
}
async function release() {
  await act(async () => {
    window.dispatchEvent(new MouseEvent("pointerup"));
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/admin/matches");
  Object.defineProperty(window, "innerWidth", { value: 1280, configurable: true });
  Object.defineProperty(window, "innerHeight", { value: 2000, configurable: true });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("AdminDataTable drag selection", () => {
  it("paints the pressed state onto every selectable row swept over, until release", async () => {
    await render();

    await press(1);
    await sweepTo(2);
    await sweepTo(3);
    await sweepTo(4);
    // Row 3 is not selectable and stays out.
    expect(selectedIds()).toEqual([1, 2, 4]);

    await release();
    await sweepTo(2);
    expect(selectedIds()).toEqual([1, 2, 4]);

    // Pressing a selected row paints deselection.
    await press(4);
    await sweepTo(2);
    await release();
    expect(selectedIds()).toEqual([1]);
  });

  it("shift-press selects the range from the last pressed row", async () => {
    await render();

    await press(1);
    await release();
    await press(4, { shiftKey: true });
    await release();
    expect(selectedIds()).toEqual([1, 2, 4]);
  });

  it("does not double-toggle on the mouse click that follows the press, but still toggles from the keyboard", async () => {
    await render();

    await press(1);
    await release();
    await act(async () => {
      checkbox(1).dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 1 }));
    });
    expect(selectedIds()).toEqual([1]);

    // Space/Enter on the button arrives as a click with `detail === 0`.
    await act(async () => {
      checkbox(1).dispatchEvent(new MouseEvent("click", { bubbles: true, detail: 0 }));
    });
    expect(selectedIds()).toEqual([]);
  });
});
