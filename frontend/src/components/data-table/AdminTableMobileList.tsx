"use client";

import React from "react";
import { flexRender, type Column, type Row } from "@tanstack/react-table";

import { cn } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID } from "@/components/data-table/columns";

/**
 * Below `md` a wide table either scrolls sideways past the point of use or
 * hides its columns, so the rows become cards instead (F18 ·1). Three columns
 * is what fits a phone row; a screen whose three most important columns are
 * not the first three passes `renderMobileCard`.
 */
export function AdminTableMobileList<TData>({
  rows,
  visibleColumns,
  renderMobileCard,
  inspectorId,
  onRowClick
}: Readonly<{
  rows: Row<TData>[];
  visibleColumns: Column<TData, unknown>[];
  renderMobileCard?: (row: Row<TData>) => React.ReactNode;
  inspectorId?: string | null;
  onRowClick?: (row: Row<TData>) => void;
}>) {
  const cardColumns = visibleColumns.filter((column) => column.id !== ADMIN_ACTION_COLUMN_ID).slice(0, 3);

  return (
    <ul aria-label="Rows">
      {rows.map((row) => {
        const cells = row.getVisibleCells();
        const actionCell = cells.find((cell) => cell.column.id === ADMIN_ACTION_COLUMN_ID);
        const body = renderMobileCard ? (
          renderMobileCard(row)
        ) : (
          <>
            {cardColumns.map((column) => {
              const cell = cells.find((candidate) => candidate.column.id === column.id);
              if (!cell) return null;
              return (
                <div key={column.id} className="truncate text-sm">
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </div>
              );
            })}
          </>
        );

        return (
          <li
            key={row.id}
            aria-current={row.id === inspectorId ? "true" : undefined}
            className={cn(
              "group flex items-start gap-2 border-b border-border/30 px-4 py-3 last:border-b-0",
              row.id === inspectorId && "bg-primary/10",
            )}
          >
            {onRowClick ? (
              <button
                type="button"
                onClick={() => onRowClick(row)}
                className="min-w-0 flex-1 space-y-0.5 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
              >
                {body}
              </button>
            ) : (
              <div className="min-w-0 flex-1 space-y-0.5">{body}</div>
            )}
            {actionCell ? (
              <div className="shrink-0">
                {flexRender(actionCell.column.columnDef.cell, actionCell.getContext())}
              </div>
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}
