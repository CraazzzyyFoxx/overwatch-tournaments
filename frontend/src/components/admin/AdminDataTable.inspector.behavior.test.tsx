// @vitest-environment happy-dom
//
// The P0-10 additions to the admin table. What is pinned here:
//  1. `inspectorId` marks the open row with `aria-current="true"` (NOT
//     `aria-selected`, which `role=table` does not allow on a row);
//  2. a `toolbar` without a `searchPlaceholder` suppresses the table's own
//     search box, so a screen never ships two search fields over one table;
//  3. passing both keeps the built-in box, for a chips-only toolbar;
//  4. below `md` the rows become cards, using `renderMobileCard` when given
//     and the first three visible columns otherwise.
// The kebab's own visibility rules live in `kit/kebab-column.behavior.test.tsx`.
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
  stage: string;
  score: string;
  status: string;
}

const ROWS: Row[] = [
  { id: 8810, stage: "Groups · R2", score: "2–1", status: "completed" },
  { id: 8812, stage: "Groups · R3", score: "—", status: "pending" }
];

const columns: ColumnDef<Row>[] = [
  { accessorKey: "id", header: "#" },
  { accessorKey: "stage", header: "Stage" },
  { accessorKey: "score", header: "Score" },
  { accessorKey: "status", header: "Status" },
  {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    cell: ({ row }) => (
      <button type="button" aria-label={`Actions for ${row.original.id}`}>
        ⋯
      </button>
    )
  }
];

let container: HTMLElement;
let root: Root;

function setViewportWidth(width: number) {
  Object.defineProperty(window, "innerWidth", { value: width, configurable: true });
  window.matchMedia = ((query: string) => ({
    matches: width < 768,
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false
  })) as unknown as typeof window.matchMedia;
}

async function render(props: Partial<React.ComponentProps<typeof AdminDataTable<Row>>> = {}) {
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
          {...props}
        />
      </QueryClientProvider>
    );
  });
}

beforeEach(() => {
  window.history.replaceState(null, "", "/admin/matches");
  setViewportWidth(1280);
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("AdminDataTable row actions and inspector", () => {
  it("marks the inspected row with aria-current, never aria-selected", async () => {
    await render({ inspectorId: "8812" });

    const current = [...container.querySelectorAll("tbody tr")].filter(
      (row) => row.getAttribute("aria-current") === "true"
    );
    expect(current).toHaveLength(1);
    expect(current[0].textContent).toContain("8812");
    expect(container.querySelector("tbody tr[aria-selected]")).toBeNull();
  });

  it("hands the search over to a toolbar that owns it", async () => {
    await render({ toolbar: <div>chips and search</div> });

    expect(container.textContent).toContain("chips and search");
    expect(container.querySelector('input[name="admin-table-search"]')).toBeNull();
  });

  it("keeps its own search when the placeholder is passed alongside a toolbar", async () => {
    await render({ toolbar: <div>chips only</div>, searchPlaceholder: "Search encounters…" });

    expect(container.querySelector('input[name="admin-table-search"]')).not.toBeNull();
  });

  it("turns rows into cards below md, using the first three columns", async () => {
    setViewportWidth(375);
    await render();

    expect(container.querySelector("table")).toBeNull();
    const cards = container.querySelectorAll("ul[aria-label='Rows'] > li");
    expect(cards).toHaveLength(2);
    // #, Stage and Score are in; Status (the fourth column) is not.
    expect(cards[1].textContent).toContain("8812");
    expect(cards[1].textContent).toContain("Groups · R3");
    expect(cards[1].textContent).not.toContain("pending");
    // The kebab still travels with the card.
    expect(cards[1].querySelector('button[aria-label="Actions for 8812"]')).not.toBeNull();
  });

  it("uses renderMobileCard when the first three columns are the wrong three", async () => {
    setViewportWidth(375);
    await render({
      renderMobileCard: (row) => <p>{`#${row.original.id} · ${row.original.status}`}</p>
    });

    const cards = container.querySelectorAll("ul[aria-label='Rows'] > li");
    expect(cards[1].textContent).toContain("#8812 · pending");
    expect(cards[1].textContent).not.toContain("Groups · R3");
  });
});
