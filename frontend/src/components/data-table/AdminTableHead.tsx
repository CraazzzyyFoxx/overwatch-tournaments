"use client";

import type { Header } from "@tanstack/react-table";
import type { MouseEvent, Ref, ThHTMLAttributes, TouchEvent } from "react";
import { flushSync } from "react-dom";

import { TableHead } from "@/components/ui/table";
import { useTranslations } from "next-intl";
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
  const t = useTranslations("kitTable.dataTableExtra");
  const resizeHandler = header.getResizeHandler();
  // TanStack drags from `getSize()`, which for a column nobody sized is its
  // 150px default, not the width it is drawn at: the live edge would jump off
  // the pointer. Pin the drawn width before the drag reads it.
  const startResize = (event: MouseEvent<HTMLDivElement> | TouchEvent<HTMLDivElement>) => {
    const { table, column } = header.getContext();
    const th = event.currentTarget.parentElement;
    if (th && table.getState().columnSizing[column.id] === undefined) {
      const width = th.getBoundingClientRect().width;
      flushSync(() => table.setColumnSizing((old) => ({ ...old, [column.id]: width })));
    }
    resizeHandler(event);
  };
  return (
    // `relative` first: a pinned header's `sticky` (also a positioning context
    // for the resize handle) must win the merge.
    <TableHead ref={ref} {...rest} className={cn("relative select-none", className)} style={style}>
      {children}
      {header.column.getCanResize() ? (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={t("resize", { id: header.column.id })}
          title={t("resizeHint")}
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={startResize}
          onTouchStart={startResize}
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
