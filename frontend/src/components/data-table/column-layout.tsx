import React from "react";
import type { Column, ColumnDef, ColumnSizingState, Table } from "@tanstack/react-table";

import { TableCell, TableHead } from "@/components/ui/table";
import { cn } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID, columnDefId, readColumnMeta } from "@/components/data-table/columns";
import type { AdminTableDensity } from "@/components/data-table/useTablePreferences";

const ADMIN_ACTION_COLUMN_MIN_WIDTH = 80;
/** Width of the select/expand column — keep in sync with its `w-10` class. */
export const ADMIN_LEADING_COLUMN_WIDTH = 40;
/** Flexible (unsized, undragged) columns split this share of the table evenly, so they read as a grid instead of shrink-wrapping to content; the filler absorbs the rest. */
const ADMIN_FLEXIBLE_FILL_PERCENT = 75;

export interface ColumnLayoutOptions<TData> {
  table: Table<TData>;
  columns: ColumnDef<TData>[];
  columnSizing: ColumnSizingState;
  hasLeadingColumn: boolean;
  density: AdminTableDensity;
}

export interface ColumnLayout<TData> {
  visibleColumns: Column<TData, unknown>[];
  /** `colSpan` of a full-width body row: every visible column, the leading column and the filler. */
  bodyColumnCount: number;
  /** Index in the visible columns the filler is rendered before. */
  fillerIndex: number;
  fillerHead: React.ReactNode;
  fillerCell: React.ReactNode;
  getColumnStyle: (column: Column<TData, unknown>) => React.CSSProperties | undefined;
  /** `left` offset per pinned column, in visible order; empty when nothing is pinned. */
  stickyLeft: Map<string, number>;
  stickyCell: (columnId: string, style?: React.CSSProperties) => { className: string | undefined; style: React.CSSProperties | undefined };
  edgePadding: (columnId: string) => string;
}

/**
 * Widths, the sticky prefix and the filler column — everything about where a
 * column sits, derived once per render and shared by the header and the body.
 */
export function buildColumnLayout<TData>({
  table,
  columns,
  columnSizing,
  hasLeadingColumn,
  density
}: ColumnLayoutOptions<TData>): ColumnLayout<TData> {
  // react-table merges an internal `defaultColumn.size` (150) into every
  // column's runtime `columnDef.size`, so that field can't tell "the caller
  // set a size" from "no one did" — check the raw prop instead.
  const explicitlySizedColumnIds = new Set(columns.filter((c) => typeof c.size === "number").map(columnDefId));

  /** Excludes the actions column, dragged/explicitly sized columns, and sticky columns (which must declare a size; see the offset loop below). */
  const isFlexibleColumn = (column: Column<TData, unknown>) =>
    column.id !== ADMIN_ACTION_COLUMN_ID &&
    columnSizing[column.id] === undefined &&
    !explicitlySizedColumnIds.has(column.id) &&
    !readColumnMeta<TData>(column.columnDef.meta).sticky;

  const getColumnStyle = (column: Column<TData, unknown>) => {
    if (column.id === ADMIN_ACTION_COLUMN_ID) {
      // Exactly as wide as its menu button, whatever a saved sizing says: the
      // column is not resizable now, but an earlier build let it be dragged.
      const width = Math.max(column.columnDef.size ?? 0, ADMIN_ACTION_COLUMN_MIN_WIDTH);
      return { width, minWidth: width, maxWidth: width };
    }
    const resized = columnSizing[column.id] !== undefined;
    if (resized || explicitlySizedColumnIds.has(column.id)) {
      const configuredSize = column.getSize();
      // Auto table layout treats `width` as a floor; a user-dragged width is a
      // ceiling too, or shrinking a column would visibly do nothing.
      return resized
        ? { width: configuredSize, minWidth: configuredSize, maxWidth: configuredSize }
        : { width: configuredSize, minWidth: configuredSize };
    }
    if (!isFlexibleColumn(column)) return undefined;
    // No explicit or dragged width: split an even share of the table so the
    // grid fills the screen instead of shrink-wrapping to content with a
    // dead gap on the right (the filler, below, absorbs what's left).
    const flexibleCount = table.getVisibleLeafColumns().filter(isFlexibleColumn).length;
    return flexibleCount > 0 ? { width: `${ADMIN_FLEXIBLE_FILL_PERCENT / flexibleCount}%` } : undefined;
  };

  const visibleColumns = table.getVisibleLeafColumns();
  // +1 for the filler column that swallows leftover width, keeping data columns
  // packed at their content width instead of stretched proportionally.
  const bodyColumnCount = visibleColumns.length + (hasLeadingColumn ? 1 : 0) + 1;
  const hasActionColumn = visibleColumns.some((column) => column.id === ADMIN_ACTION_COLUMN_ID);
  /** Filler goes in front of the actions column, or at the very end without one. */
  const fillerIndex = hasActionColumn ? visibleColumns.length - 1 : visibleColumns.length;

  // Sticky pins a left-edge PREFIX of the visible columns: a pinned column with
  // scrolling ones in front of it would park itself over the wrong neighbours.
  // Offsets are summed from declared (or dragged) sizes rather than measured,
  // so every pinned column after the first must set `size`.
  const stickyLeft = new Map<string, number>();
  let stickyOffset = hasLeadingColumn ? ADMIN_LEADING_COLUMN_WIDTH : 0;
  for (const column of visibleColumns) {
    if (!readColumnMeta<TData>(column.columnDef.meta).sticky) break;
    stickyLeft.set(column.id, stickyOffset);
    const width = getColumnStyle(column)?.width;
    stickyOffset += typeof width === "number" ? width : 0;
  }
  const lastStickyId = [...stickyLeft.keys()].pop() ?? null;
  // The pinned block ends in a hard edge that scrolling content slides under;
  // the default 8px on either side of it reads as none, so both neighbours of
  // the edge get the same inset the table's outer edges have.
  const firstScrollingId = lastStickyId ? (visibleColumns[stickyLeft.size]?.id ?? null) : null;
  const edgePadding = (columnId: string) =>
    cn(columnId === lastStickyId && "pr-4", columnId === firstScrollingId && "pl-4");

  /** Sticky class + `left` for a data cell, or nothing when it is not pinned. */
  const stickyCell = (columnId: string, style?: React.CSSProperties) => {
    const left = stickyLeft.get(columnId);
    if (left === undefined) return { className: undefined, style };
    return {
      className: cn("admin-sticky-col", columnId === lastStickyId && "admin-sticky-col-edge"),
      style: { ...style, left }
    };
  };

  // Auto table layout hands leftover width to every column in proportion to
  // its content, which reads as random gaps between columns. Flexible columns
  // (see `getColumnStyle`) now claim an even `ADMIN_FLEXIBLE_FILL_PERCENT`
  // share instead, so the grid fills the screen; the filler only mops up
  // whatever's left over (all of it, if every column turned out sized/sticky).
  const flexibleColumnCount = visibleColumns.filter(isFlexibleColumn).length;
  const fillerStyle = flexibleColumnCount > 0 ? { width: `${100 - ADMIN_FLEXIBLE_FILL_PERCENT}%` } : undefined;
  const fillerHead = (
    <TableHead
      key="filler"
      aria-hidden
      className={cn("border-b border-border/40 p-0 admin-table-head", !fillerStyle && "w-full", density === "compact" ? "h-8" : "h-9")}
      style={fillerStyle}
    />
  );
  const fillerCell = <TableCell key="filler" aria-hidden className={cn("p-0", !fillerStyle && "w-full")} style={fillerStyle} />;

  return {
    visibleColumns,
    bodyColumnCount,
    fillerIndex,
    fillerHead,
    fillerCell,
    getColumnStyle,
    stickyLeft,
    stickyCell,
    edgePadding
  };
}
