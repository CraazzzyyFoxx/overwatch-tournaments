"use client";

import type { Header } from "@tanstack/react-table";
import type { Ref, ThHTMLAttributes } from "react";

import { TableHead } from "@/components/ui/table";
import { cn } from "@/components/data-table/host";

export type AdminTableHeadProps<TData> = {
  header: Header<TData, unknown>;
  ref?: Ref<HTMLTableCellElement>;
} & ThHTMLAttributes<HTMLTableCellElement>;

/**
 * Header cell with a resize handle on its right edge.
 *
 * Deliberately free of `@dnd-kit`: the draggable variant (`SortableHead` in
 * `ColumnDnd.tsx`) renders this one with the sortable bindings applied, and
 * lives in its own chunk so the drag machinery is not downloaded by every
 * admin list page that never reorders a column.
 */
export function AdminTableHead<TData>({
  header,
  className,
  style,
  children,
  ref,
  ...rest
}: Readonly<AdminTableHeadProps<TData>>) {
  const resizeHandler = header.getResizeHandler();
  return (
    <TableHead ref={ref} {...rest} className={cn(className, "relative select-none")} style={style}>
      {children}
      {header.column.getCanResize() ? (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={`Resize ${header.column.id} column`}
          title="Drag to resize, double-click to reset"
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={resizeHandler}
          onTouchStart={resizeHandler}
          onDoubleClick={() => header.column.resetSize()}
          className={cn(
            "absolute right-0 top-0 h-full w-1.5 cursor-col-resize touch-none hover:bg-primary/40",
            header.column.getIsResizing() && "bg-primary"
          )}
        />
      ) : null}
    </TableHead>
  );
}
