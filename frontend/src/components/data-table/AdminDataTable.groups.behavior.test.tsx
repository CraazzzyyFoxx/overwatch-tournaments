// @vitest-environment happy-dom
//
// Grouped rows: a group header folds its rows away and brings them back,
// and only its own rows.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ColumnDef, Row as TableRow } from "@tanstack/react-table";
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DataTable } from "@/components/data-table/DataTable";
import type { DataTableGroup } from "@/components/data-table/types";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/navigation", () => ({
  usePathname: () => "/admin/groups"
}));

interface Row {
  id: number;
  name: string;
  role: string;
}

const ROWS: Row[] = [
  { id: 1, name: "Ana", role: "tank" },
  { id: 2, name: "Bo", role: "tank" },
  { id: 3, name: "Cy", role: "support" }
];

const columns: ColumnDef<Row>[] = [{ accessorKey: "name", header: "Name" }];

const byRole = (rows: TableRow<Row>[]): DataTableGroup<Row>[] =>
  ["tank", "support"].map((role) => ({
    key: role,
    label: role,
    rows: rows.filter((row) => row.original.role === role)
  }));

let container: HTMLElement;
let root: Root;

const header = (role: string) =>
  [...container.querySelectorAll<HTMLButtonElement>("tbody button[aria-expanded]")].find((button) =>
    button.textContent?.startsWith(role)
  )!;
const shownIds = () =>
  [...container.querySelectorAll<HTMLElement>("tbody tr[data-row-id]")].map((row) => row.dataset.rowId);

beforeEach(async () => {
  window.history.replaceState(null, "", "/admin/groups");
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(
      <QueryClientProvider client={new QueryClient()}>
        <DataTable<Row>
          rows={ROWS}
          columns={columns}
          getRowId={(row) => String(row.id)}
          paging="all"
          groupRows={byRole}
        />
      </QueryClientProvider>
    );
  });
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("DataTable groups", () => {
  it("folds one group's rows behind its header and unfolds them again", async () => {
    expect(header("tank").textContent).toBe("tank2");
    expect(header("tank").getAttribute("aria-expanded")).toBe("true");
    expect(shownIds()).toEqual(["1", "2", "3"]);

    await act(async () => header("tank").click());
    expect(header("tank").getAttribute("aria-expanded")).toBe("false");
    expect(shownIds()).toEqual(["3"]);
    // The first row on screen takes the Tab stop when the first group is folded.
    expect(container.querySelector("tbody tr[data-row-id='3']")?.getAttribute("tabindex")).toBe("0");

    await act(async () => header("tank").click());
    expect(shownIds()).toEqual(["1", "2", "3"]);
  });
});
