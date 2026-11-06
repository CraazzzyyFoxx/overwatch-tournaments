// @vitest-environment happy-dom
//
// Flexible (unsized, unsticky, undragged) admin-table columns split the
// table evenly instead of shrink-wrapping to content with a dead gap on the
// right: 75% when a filler has the actions column after it, all of it when
// the filler would trail; an explicitly-sized column keeps its own width.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataTable } from "@/components/data-table/DataTable";

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

async function render(tableColumns = columns) {
  const client = new QueryClient();
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={client}>
        <DataTable<Row> rows={rows} columns={tableColumns} getRowId={(r) => r.id} />
      </QueryClientProvider>
    );
  });
}

afterEach(() => {
  act(() => root.unmount());
  container.remove();
});

describe("DataTable column widths", () => {
  it("splits unsized columns evenly and leaves an explicitly-sized column alone", async () => {
    await render();

    // Nothing after the filler: the two flexible columns (when, action) share it all.
    expect(header("When").style.width).toBe("50%");
    expect(header("Action").style.width).toBe("50%");
    // Explicitly sized column keeps its own pixel width, untouched.
    expect(header("Actor").style.width).toBe("300px");
  });

  it("leaves a quarter to the filler in front of the actions column", async () => {
    await render([...columns, { id: "actions", header: "Actions", cell: () => null }]);

    expect(header("When").style.width).toBe("37.5%");
    expect(header("Action").style.width).toBe("37.5%");
  });

  function header(label: string) {
    return [...container.querySelectorAll("thead th")].find((h) => h.textContent?.includes(label)) as HTMLElement;
  }

  function drag(th: HTMLElement, steps: number[]) {
    const handle = th.querySelector('[role="separator"]') as HTMLElement;
    act(() => {
      handle.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, clientX: 0 }));
    });
    for (const clientX of steps) {
      act(() => {
        document.dispatchEvent(new MouseEvent("mousemove", { bubbles: true, clientX }));
      });
    }
  }

  function release(clientX: number) {
    act(() => {
      document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, clientX }));
    });
  }

  it("redraws a dragged column while the pointer moves, then keeps that width on release", async () => {
    localStorage.clear();
    await render();
    const actor = header("Actor");
    vi.spyOn(actor, "getBoundingClientRect").mockReturnValue({ width: 300 } as DOMRect);
    drag(actor, [40, 80]);
    expect(header("Actor").style.width).toBe("380px");
    release(80);
    expect(header("Actor").style.width).toBe("380px");
  });

  it("starts dragging a flexible column from the width it is drawn at", async () => {
    localStorage.clear();
    await render();
    const when = header("When");
    vi.spyOn(when, "getBoundingClientRect").mockReturnValue({ width: 240 } as DOMRect);
    drag(when, [10]);
    expect(header("When").style.width).toBe("250px");
    release(10);
  });
});
