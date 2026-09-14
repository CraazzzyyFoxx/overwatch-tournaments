// @vitest-environment happy-dom
//
// The single row-actions convention. What is pinned here:
//  1. the trigger is always in the DOM and reachable without a mouse: quiet
//     until the row is hovered, but revealed whenever the row holds focus and
//     on touch devices, which have neither hover nor focus-within;
//  2. its accessible name names the row, so nine identical "Actions" buttons
//     are distinguishable;
//  3. a `hidden` action is absent, not disabled — permission gating must not
//     advertise what the user cannot do;
//  4. an `href` action renders a real link, not an onClick handler.
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import type { ColumnDef } from "@tanstack/react-table";
import { getCoreRowModel, useReactTable } from "@tanstack/react-table";
import { Pencil, Trash2 } from "lucide-react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createKebabColumn } from "./kebab-column";

declare global {
  var IS_REACT_ACT_ENVIRONMENT: boolean;
}
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: React.ReactNode }) => (
    <a href={href}>{children}</a>
  )
}));

interface Row {
  id: number;
  name: string;
}

const onEdit = vi.fn();
const rows: Row[] = [{ id: 8812, name: "Encounter #8812" }];

let container: HTMLElement;
let root: Root;

function Harness({ column }: { readonly column: ColumnDef<Row> }) {
  const table = useReactTable<Row>({
    data: rows,
    columns: [{ accessorKey: "name", header: "Name" }, column],
    getCoreRowModel: getCoreRowModel(),
    getRowId: (row) => String(row.id)
  });

  return (
    <table>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id}>
                {typeof cell.column.columnDef.cell === "function"
                  ? cell.column.columnDef.cell(cell.getContext())
                  : cell.renderValue<string>()}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

async function render(column: ColumnDef<Row>) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<Harness column={column} />);
  });
}

/** Radix's dropdown trigger opens on `pointerdown`, not `click`. */
async function click(element: Element | null | undefined) {
  await act(async () => {
    element?.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true }));
    element?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
  });
}

function trigger() {
  return container.querySelector<HTMLButtonElement>("button[aria-label^='Actions for']");
}

beforeEach(() => {
  onEdit.mockClear();
});

afterEach(async () => {
  await act(async () => {
    root.unmount();
  });
  container.remove();
  document.body.innerHTML = "";
});

describe("createKebabColumn", () => {
  it("names the trigger after the row", async () => {
    await render(
      createKebabColumn<Row>(
        () => [{ label: "Edit", icon: Pencil, onSelect: onEdit }],
        { rowLabel: (row) => row.name }
      )
    );

    expect(trigger()?.getAttribute("aria-label")).toBe("Actions for Encounter #8812");
  });

  it("falls back to the row id when no label is supplied", async () => {
    await render(createKebabColumn<Row>(() => [{ label: "Edit", onSelect: onEdit }]));

    expect(trigger()?.getAttribute("aria-label")).toBe("Actions for row 8812");
  });

  it("is reachable without hover: revealed on row focus and on touch", async () => {
    await render(createKebabColumn<Row>(() => [{ label: "Edit", onSelect: onEdit }]));

    expect(trigger()?.className).toContain("group-focus-within:opacity-100");
    expect(trigger()?.className).toContain("[@media(hover:none)]:opacity-100");
  });

  it("omits hidden actions instead of disabling them", async () => {
    await render(
      createKebabColumn<Row>(() => [
        { label: "Edit", onSelect: onEdit },
        { label: "Delete", icon: Trash2, onSelect: () => undefined, destructive: true, hidden: true }
      ])
    );

    await click(trigger());
    const items = [...document.querySelectorAll("[role='menuitem']")].map((item) =>
      item.textContent?.trim()
    );
    expect(items).toEqual(["Edit"]);
  });

  it("renders nothing when every action is hidden", async () => {
    await render(
      createKebabColumn<Row>(() => [{ label: "Edit", onSelect: onEdit, hidden: true }])
    );

    expect(trigger()).toBeNull();
  });

  it("renders an href action as a link", async () => {
    await render(
      createKebabColumn<Row>(() => [{ label: "Open page", href: "/admin/encounters/8812" }])
    );

    await click(trigger());
    const link = [...document.querySelectorAll("a")].find((anchor) =>
      anchor.textContent?.includes("Open page")
    );
    expect(link?.getAttribute("href")).toBe("/admin/encounters/8812");
  });
});
