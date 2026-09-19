// @vitest-environment happy-dom
//
// Flexible (unsized, unsticky, undragged) admin-table columns split
// ADMIN_FLEXIBLE_FILL_PERCENT evenly instead of shrink-wrapping to content
// with a dead gap on the right; an explicitly-sized column keeps its own
// width untouched.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AdminDataTable } from "@/components/data-table/AdminDataTable";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/__column-width-test"
}));

interface Row {
  id: number;
  when: string;
  action: string;
  actor: string;
}

const rows: Row[] = [{ id: 1, when: "now", action: "did thing", actor: "someone" }];

const columns: ColumnDef<Row>[] = [
  { id: "when", accessorKey: "when", header: "When" },
  { id: "action", accessorKey: "action", header: "Action" },
  { id: "actor", accessorKey: "actor", header: "Actor", size: 300 },
];

let container: HTMLElement;
let root: Root;

async function render() {
  const client = new QueryClient();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <AdminDataTable<Row> rows={rows} columns={columns} getRowId={(r) => r.id} />
      </QueryClientProvider>
    );
  });
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("AdminDataTable column widths", () => {
  it("splits unsized columns evenly and leaves an explicitly-sized column alone", async () => {
    await render();
    const headers = [...container.querySelectorAll("thead th")];
    const when = headers.find((h) => h.textContent?.includes("When")) as HTMLElement;
    const action = headers.find((h) => h.textContent?.includes("Action")) as HTMLElement;
    const actor = headers.find((h) => h.textContent?.includes("Actor")) as HTMLElement;

    // Two flexible columns (when, action) share 75% evenly -> 37.5% each.
    expect(when.style.width).toBe("37.5%");
    expect(action.style.width).toBe("37.5%");
    // Explicitly sized column keeps its own pixel width, untouched.
    expect(actor.style.width).toBe("300px");
  });
});
