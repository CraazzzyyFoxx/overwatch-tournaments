import React from "react";
import type { Column, ColumnDef, ColumnSizingState } from "@tanstack/react-table";

import { TableCell, TableHead } from "@/components/ui/table";
import { cn } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID, columnDefId, readColumnMeta } from "@/components/data-table/columns";
import type { AdminTableDensity } from "@/components/data-table/useTablePreferences";

const ADMIN_ACTION_COLUMN_MIN_WIDTH = 80;
/** Width of the select/expand column — keep in sync with its `w-10` class. */
const ADMIN_LEADING_COLUMN_WIDTH = 40;
/** Flexible (unsized, undragged) columns split this share of the table evenly, so they read as a grid instead of shrink-wrapping to content; the filler absorbs the rest. */
const ADMIN_FLEXIBLE_FILL_PERCENT = 75;

/**
 * A pinned cell sits ON TOP of the columns scrolling past it, so it is opaque:
 * `--admin-sticky-bg`, set on the table's root, is the translucent card
 * flattened over the page (or the solid card when `framed={false}`). The row's
 * state tint (`--admin-row-tint`, see `body-rows.tsx`) is painted over that
 * base as an image layer: the same compositing the scrolling cells get from
 * the row's own background, so the pinned block and the rest land on one colour.
 */
export const STICKY_CELL_CLASS =
  "sticky z-2 bg-[color:var(--admin-sticky-bg)] bg-[linear-gradient(var(--admin-row-tint),var(--admin-row-tint))] transition-colors";

/** Every header cell shares that surface, under a muted wash: the header sticks to the top of the scroll box, so a translucent one would show the rows passing under it. */
export const HEAD_SURFACE_CLASS = "bg-[color:color-mix(in_srgb,hsl(var(--muted))_20%,var(--admin-sticky-bg))]";

/** A pinned header cell: above the pinned body cells, since it holds both axes at the corner. */
export const STICKY_HEAD_CLASS = cn(STICKY_CELL_CLASS, "z-3", HEAD_SURFACE_CLASS);

/** The pinned block's inner edge: the only cue that the rest scrolls under it. */
const STICKY_EDGE_CLASS = {
  left: "shadow-[inset_-1px_0_0_hsl(var(--border))]",
  right: "shadow-[inset_1px_0_0_hsl(var(--border))]"
} as const;

/** What `stickyCell` hands a cell: its classes and offset, plus `data-sticky` (`left`/`right`) and `data-sticky-edge` on the block's inner edge. */
export interface StickyCellProps {
  className: string | undefined;
  style: React.CSSProperties | undefined;
  "data-sticky"?: "left" | "right";
  "data-sticky-edge"?: "";
}

export interface ColumnLayoutOptions<TData> {
  /** `table.getVisibleLeafColumns()`, which TanStack keeps as one array until visibility, order or the columns change. */
  visibleColumns: Column<TData, unknown>[];
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
  /** `right` offset per right-pinned column (the actions column included), from the edge inward; empty when nothing pins right. */
  stickyRight: Map<string, number>;
  stickyCell: (columnId: string, style?: React.CSSProperties) => StickyCellProps;
  edgePadding: (columnId: string) => string;
}

/**
 * Widths, the sticky prefix and the filler column — everything about where a
 * column sits, shared by the header and the body. Pure in its options, so
 * `DataTable` memoises it and the memoised body rows keep their props.
 */
export function buildColumnLayout<TData>({
  visibleColumns,
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
    const dragged = columnSizing[column.id];
    const resized = dragged !== undefined;
    if (resized || explicitlySizedColumnIds.has(column.id)) {
      // The map, not `column.getSize()`: mid-drag it carries the live width.
      // Clamped the way `getSize()` clamps a committed one.
      const { minSize = 0, maxSize = Number.MAX_SAFE_INTEGER } = column.columnDef;
      const configuredSize = resized ? Math.min(Math.max(dragged, minSize), maxSize) : column.getSize();
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
    const flexibleCount = visibleColumns.filter(isFlexibleColumn).length;
    return flexibleCount > 0 ? { width: `${ADMIN_FLEXIBLE_FILL_PERCENT / flexibleCount}%` } : undefined;
  };

  // +1 for the filler column that swallows leftover width, keeping data columns
  // packed at their content width instead of stretched proportionally.
  const bodyColumnCount = visibleColumns.length + (hasLeadingColumn ? 1 : 0) + 1;
  const hasActionColumn = visibleColumns.some((column) => column.id === ADMIN_ACTION_COLUMN_ID);

  // Sticky pins a left-edge PREFIX of the visible columns: a pinned column with
  // scrolling ones in front of it would park itself over the wrong neighbours.
  // Offsets are summed from declared (or dragged) sizes rather than measured,
  // so every pinned column after the first must set `size`.
  const stickyLeft = new Map<string, number>();
  let stickyOffset = hasLeadingColumn ? ADMIN_LEADING_COLUMN_WIDTH : 0;
  for (const column of visibleColumns) {
    const { sticky } = readColumnMeta<TData>(column.columnDef.meta);
    if (!sticky || sticky === "right") break;
    stickyLeft.set(column.id, stickyOffset);
    const width = getColumnStyle(column)?.width;
    stickyOffset += typeof width === "number" ? width : 0;
  }
  const lastStickyId = [...stickyLeft.keys()].pop() ?? null;

  // `sticky: "right"` mirrors that on a right-edge SUFFIX. The actions column
  // always sits last, so it pins at `right: 0` under any right-pinned column —
  // otherwise that column would park over it.
  const stickyRight = new Map<string, number>();
  let stickyRightOffset = 0;
  for (const column of [...visibleColumns].reverse()) {
    if (column.id !== ADMIN_ACTION_COLUMN_ID && readColumnMeta<TData>(column.columnDef.meta).sticky !== "right") break;
    stickyRight.set(column.id, stickyRightOffset);
    const width = getColumnStyle(column)?.width;
    stickyRightOffset += typeof width === "number" ? width : 0;
  }
  // The actions column on its own is not a pinned block.
  if (hasActionColumn && stickyRight.size === 1) stickyRight.clear();
  const firstStickyRightId = [...stickyRight.keys()].pop() ?? null;

  /** Filler goes in front of the right-pinned block, else of the actions column, else at the very end. */
  const fillerIndex = visibleColumns.length - (stickyRight.size > 0 ? stickyRight.size : Number(hasActionColumn));

  // A pinned block ends in a hard edge that scrolling content slides under;
  // the default 8px on either side of it reads as none, so both neighbours of
  // each edge get the same inset the table's outer edges have.
  const firstScrollingId = lastStickyId ? (visibleColumns[stickyLeft.size]?.id ?? null) : null;
  const lastScrollingId = firstStickyRightId ? (visibleColumns[fillerIndex - 1]?.id ?? null) : null;
  const edgePadding = (columnId: string) =>
    cn(
      (columnId === lastStickyId || columnId === lastScrollingId) && "pr-4",
      (columnId === firstScrollingId || columnId === firstStickyRightId) && "pl-4"
    );

  /** Sticky classes, `left`/`right` and the `data-sticky*` marks for a cell, or just its style when it is not pinned. */
  const stickyCell = (columnId: string, style?: React.CSSProperties): StickyCellProps => {
    const left = stickyLeft.get(columnId);
    if (left !== undefined) {
      const edge = columnId === lastStickyId;
      return {
        className: cn(STICKY_CELL_CLASS, edge && STICKY_EDGE_CLASS.left),
        style: { ...style, left },
        "data-sticky": "left",
        "data-sticky-edge": edge ? "" : undefined
      };
    }
    const right = stickyRight.get(columnId);
    if (right === undefined) return { className: undefined, style };
    const edge = columnId === firstStickyRightId;
    return {
      className: cn(STICKY_CELL_CLASS, edge && STICKY_EDGE_CLASS.right),
      style: { ...style, right },
      "data-sticky": "right",
      "data-sticky-edge": edge ? "" : undefined
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
      className={cn("border-b border-border/40 p-0", HEAD_SURFACE_CLASS, !fillerStyle && "w-full", density === "compact" ? "h-8" : "h-9")}
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
    stickyRight,
    stickyCell,
    edgePadding
  };
}
