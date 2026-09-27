import { flexRender, type Header, type SortingState } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

import { cn } from "@/components/data-table/host";
import { ariaSortValue } from "@/components/data-table/types";
import { ADMIN_ACTION_COLUMN_ID, ALIGN_CLASS, ALIGN_FLEX_CLASS, RESPONSIVE_CLASS, readColumnMeta } from "@/components/data-table/columns";
import type { ColumnLayout } from "@/components/data-table/column-layout";
import type { AdminTableDensity } from "@/components/data-table/useTablePreferences";
import type { ColumnDndModule } from "@/components/data-table/ColumnDnd";

export interface HeadCellContext<TData> {
  layout: ColumnLayout<TData>;
  density: AdminTableDensity;
  sorting: SortingState;
  /** Client mode stacks sorts on Shift+click; server mode takes one column. */
  isClientMode: boolean;
  hasLeadingColumn: boolean;
  /** Plain until the drag chunk lands, then the same cell with dnd-kit's bindings. */
  HeadCell: ColumnDndModule["SortableHead"];
}

/** One `<th>`: the column's header, its sort toggle and its resize handle. */
export function renderHeadCell<TData>(
  header: Header<TData, unknown>,
  index: number,
  count: number,
  { layout, density, sorting, isClientMode, hasLeadingColumn, HeadCell }: HeadCellContext<TData>
) {
  const isActionColumn = header.column.id === ADMIN_ACTION_COLUMN_ID;
  const isFirstColumn = index === 0 && !hasLeadingColumn;
  const isLastColumn = index === count - 1;
  const canSort = header.column.getCanSort();
  const sorted = header.column.getIsSorted();
  const sortIndex = sorting.length > 1 ? header.column.getSortIndex() : -1;
  const columnMeta = readColumnMeta<TData>(header.column.columnDef.meta);
  const align = columnMeta.align ?? (isActionColumn ? "right" : "left");
  const sticky = layout.stickyCell(header.column.id, layout.getColumnStyle(header.column));

  return (
    <HeadCell
      key={header.id}
      header={header}
      aria-sort={canSort ? ariaSortValue(sorted) : undefined}
      className={cn(
        "border-b border-border/40 text-xs font-medium text-muted-foreground",
        density === "compact" ? "h-8" : "h-9",
        sticky.className ?? "admin-table-head",
        isFirstColumn && "pl-4",
        isLastColumn && "pr-4",
        layout.edgePadding(header.column.id),
        ALIGN_CLASS[align],
        RESPONSIVE_CLASS[columnMeta.responsive ?? "always"],
        columnMeta.className,
      )}
      style={sticky.style}
    >
      {header.isPlaceholder ? null : (
        <span className={cn("inline-flex w-full items-center gap-1", ALIGN_FLEX_CLASS[align])}>
          {canSort ? (
            <button
              type="button"
              onClick={header.column.getToggleSortingHandler()}
              title={isClientMode ? "Click to sort, Shift+click to add a second sort" : undefined}
              className={cn(
                "inline-flex items-center gap-1 rounded transition-colors hover:text-foreground",
                sorted ? "text-foreground" : "text-muted-foreground",
              )}
            >
              {flexRender(header.column.columnDef.header, header.getContext())}
              {sorted === "asc" ? (
                <ArrowUp aria-hidden className="size-3 shrink-0" />
              ) : sorted === "desc" ? (
                <ArrowDown aria-hidden className="size-3 shrink-0" />
              ) : (
                <ArrowUpDown aria-hidden className="size-3 shrink-0 opacity-30" />
              )}
              {sortIndex >= 0 ? (
                <span aria-label={`Sort priority ${sortIndex + 1}`} className="font-mono text-[10px] tabular-nums opacity-70">{sortIndex + 1}</span>
              ) : null}
            </button>
          ) : (
            flexRender(header.column.columnDef.header, header.getContext())
          )}
        </span>
      )}
    </HeadCell>
  );
}
