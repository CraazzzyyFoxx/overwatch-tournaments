"use client";

import React from "react";
import type { Row, SortingState, Table } from "@tanstack/react-table";

import { TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID } from "@/components/data-table/columns";
import { AdminTableHead } from "@/components/data-table/AdminTableHead";
import { renderHeadCell } from "@/components/data-table/head-cell";
import type { ColumnLayout } from "@/components/data-table/column-layout";
import type { AdminTableDensity } from "@/components/data-table/useTablePreferences";
import type { ColumnDndModule } from "@/components/data-table/ColumnDnd";

export interface AdminTableHeaderProps<TData> {
  table: Table<TData>;
  layout: ColumnLayout<TData>;
  density: AdminTableDensity;
  sorting: SortingState;
  isClientMode: boolean;
  hasLeadingColumn: boolean;
  enableRowSelection: boolean;
  /** Rows the select-all checkbox covers — the selectable ones on this page. */
  selectableRows: Row<TData>[];
  /** Resolved reorder chunk, or null while the header is still plain. */
  columnDnd: ColumnDndModule | null;
  onReorder: (activeId: string, overId: string) => void;
  onArmDnd: () => void;
}

/** The sticky header row: select-all, the column headers, and the drag context around them. */
export function AdminTableHeader<TData>({
  table,
  layout,
  density,
  sorting,
  isClientMode,
  hasLeadingColumn,
  enableRowSelection,
  selectableRows,
  columnDnd,
  onReorder,
  onArmDnd
}: Readonly<AdminTableHeaderProps<TData>>) {
  const headCellContext = {
    layout,
    density,
    sorting,
    isClientMode,
    hasLeadingColumn,
    // Plain until the drag chunk lands; `SortableHead` renders the same cell
    // with dnd-kit's bindings on it.
    HeadCell: columnDnd?.SortableHead ?? AdminTableHead
  };

  return (
    <TableHeader className="sticky top-0 z-10" onPointerDown={onArmDnd}>
      <ColumnDndBoundary
        columnDnd={columnDnd}
        columnIds={layout.visibleColumns.filter((column) => column.id !== ADMIN_ACTION_COLUMN_ID).map((column) => column.id)}
        onReorder={onReorder}
      >
      {table.getHeaderGroups().map((headerGroup) => (
        <TableRow key={headerGroup.id} className="hover:bg-transparent">
          {hasLeadingColumn ? (
            <TableHead
              className={cn(
                "w-10 min-w-10 border-b border-border/40 pl-4 pr-2 text-left",
                density === "compact" ? "h-8" : "h-9",
                layout.stickyLeft.size > 0 ? "admin-sticky-col" : "admin-table-head"
              )}
              style={layout.stickyLeft.size > 0 ? { left: 0 } : undefined}
            >
              {enableRowSelection ? (
                <Checkbox
                  checked={
                    selectableRows.length > 0 &&
                    selectableRows.every((row) => row.getIsSelected())
                  }
                  disabled={selectableRows.length === 0}
                  onCheckedChange={(checked) =>
                    selectableRows.forEach((row) => row.toggleSelected(checked === true))
                  }
                  aria-label="Select visible selectable rows"
                />
              ) : null}
            </TableHead>
          ) : null}
          {headerGroup.headers.flatMap((header, index) => [
            ...(index === layout.fillerIndex ? [layout.fillerHead] : []),
            renderHeadCell(header, index, headerGroup.headers.length, headCellContext)
          ])}
          {layout.fillerIndex === headerGroup.headers.length ? layout.fillerHead : null}
        </TableRow>
      ))}
      </ColumnDndBoundary>
    </TableHeader>
  );
}

/**
 * Renders the header rows inside dnd-kit's contexts once the reorder chunk has
 * resolved, and bare until then.
 *
 * The swap remounts the header rows once (React cannot keep a subtree's
 * identity when its ancestor appears). It sits inside `<thead>` so the scroll
 * box and the body — scroll position, virtualised rows, row focus — survive it.
 */
function ColumnDndBoundary({
  columnDnd,
  columnIds,
  onReorder,
  children
}: Readonly<{
  columnDnd: ColumnDndModule | null;
  columnIds: string[];
  onReorder: (activeId: string, overId: string) => void;
  children: React.ReactNode;
}>) {
  if (!columnDnd) return children;

  const { ColumnDndProvider } = columnDnd;
  return (
    <ColumnDndProvider columnIds={columnIds} onReorder={onReorder}>
      {children}
    </ColumnDndProvider>
  );
}
