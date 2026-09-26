"use client";

import React from "react";
import type { Row } from "@tanstack/react-table";
import type { VirtualItem, Virtualizer } from "@tanstack/react-virtual";

import { TableCell, TableRow } from "@/components/ui/table";
import { cn, EYEBROW_CLASS } from "@/components/data-table/host";
import type { KebabAction } from "@/components/data-table/kebab-column";
import { AdminRowContextMenu } from "@/components/data-table/AdminRowContextMenu";
import { renderBodyCell, renderLeadingCell, type BodyCellContext, type LeadingCellContext } from "@/components/data-table/body-cells";
import type { ColumnLayout } from "@/components/data-table/column-layout";
import type { RowSelectionGestures } from "@/components/data-table/useRowSelectionGestures";
import type { BodyItem } from "@/components/data-table/useVirtualBody";

export interface BodyRowContext<TData> {
  layout: ColumnLayout<TData>;
  cell: BodyCellContext<TData>;
  /** Absent when the table has no leading column at all. */
  leading?: LeadingCellContext<TData>;
  virtualizer: Virtualizer<HTMLElement, Element>;
  gestures: RowSelectionGestures<TData>;
  /** Row open in the inspector: tinted and `aria-current`. */
  inspectorId?: string | null;
  /** The one row in the Tab order; arrows move between the rest. */
  tabbableRowId: string | null;
  onRowFocus: (rowId: string) => void;
  hasRowAction: boolean;
  onRowClick: (event: React.MouseEvent<HTMLTableRowElement>, row: Row<TData>) => void;
  onRowDoubleClick: (event: React.MouseEvent<HTMLTableRowElement>, row: Row<TData>) => void;
  /** Text of the cell under the last right-click, offered as "Copy" in the row menu. */
  contextCell: string;
  onContextCellChange: (text: string) => void;
  rowActions?: (row: TData) => KebabAction[];
  rowHintId: string;
  renderExpanded?: (row: Row<TData>) => React.ReactNode;
}

/**
 * Turns one body item — a row, a group header or an expanded detail — into its
 * `<tr>`. Virtualised items carry the measuring ref and their index.
 */
export function createBodyRenderer<TData>(ctx: BodyRowContext<TData>) {
  const renderRow = (row: Row<TData>, virtual?: VirtualItem) => {
    const cells = row.getVisibleCells();
    const tr = (
      <TableRow
        ref={virtual ? ctx.virtualizer.measureElement : undefined}
        data-index={virtual?.index}
        data-row-id={row.id}
        data-selected={row.getIsSelected() || undefined}
        aria-current={row.id === ctx.inspectorId ? "true" : undefined}
        tabIndex={row.id === ctx.tabbableRowId ? 0 : -1}
        onFocus={(event) => { if (event.target === event.currentTarget) ctx.onRowFocus(row.id); }}
        className={cn(
          // Tints (hover / selected / current) live in `data-table.css` under
          // `.admin-row`: the pinned cells are opaque and must repaint the very
          // same colour, and two copies of it drifted apart.
          "admin-row group border-b border-border/30",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 focus-visible:ring-inset",
          ctx.hasRowAction && "cursor-pointer",
        )}
        onPointerDown={ctx.gestures.rowPointerDown(row)}
        onClick={(event) => ctx.onRowClick(event, row)}
        onDoubleClick={(event) => ctx.onRowDoubleClick(event, row)}
        onContextMenu={(event) => {
          const td = (event.target as HTMLElement).closest("td");
          ctx.onContextCellChange(td ? td.textContent.trim() : "");
        }}
        aria-describedby={ctx.rowHintId}
      >
        {ctx.leading ? renderLeadingCell(row, ctx.leading) : null}
        {cells.flatMap((cell, index) => [
          ...(index === ctx.layout.fillerIndex ? [ctx.layout.fillerCell] : []),
          renderBodyCell(cell, index, cells.length, ctx.cell)
        ])}
        {ctx.layout.fillerIndex === cells.length ? ctx.layout.fillerCell : null}
      </TableRow>
    );
    return (
      <AdminRowContextMenu
        key={row.id}
        cells={cells}
        contextCell={ctx.contextCell}
        actions={ctx.rowActions?.(row.original).filter((action) => !action.hidden) ?? []}
      >
        {tr}
      </AdminRowContextMenu>
    );
  };

  const renderItem = (item: BodyItem<TData>, virtual?: VirtualItem) => {
    const measure = virtual ? { ref: ctx.virtualizer.measureElement, "data-index": virtual.index } : {};
    if (item.kind === "row") return renderRow(item.row, virtual);
    if (item.kind === "group") {
      return (
        <TableRow key={item.key} {...measure} className="hover:bg-transparent">
          <TableCell colSpan={ctx.layout.bodyColumnCount} className={cn(EYEBROW_CLASS, "border-b border-border/40 bg-muted/30 py-2 pl-4")}>
            {item.group.label}
          </TableCell>
        </TableRow>
      );
    }
    return (
      <TableRow key={item.key} {...measure} className="hover:bg-transparent">
        <TableCell colSpan={ctx.layout.bodyColumnCount} className="border-b border-border/30 bg-muted/10 px-4 py-4">
          {ctx.renderExpanded?.(item.row)}
        </TableCell>
      </TableRow>
    );
  };

  return renderItem;
}
