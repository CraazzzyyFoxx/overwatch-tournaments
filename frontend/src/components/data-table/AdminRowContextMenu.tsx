"use client";

import React from "react";
import type { Cell } from "@tanstack/react-table";
import { Copy, Rows3 } from "lucide-react";

import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { cn, Link } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID } from "@/components/data-table/columns";
import type { KebabAction } from "@/components/data-table/kebab-column";

/**
 * Right-click / long-press menu on a row: the cell under the pointer, the row
 * as a spreadsheet line, and whatever the kebab column offers.
 */
export function AdminRowContextMenu<TData>({
  cells,
  contextCell,
  actions,
  children
}: Readonly<{
  cells: Cell<TData, unknown>[];
  /** Text of the cell under the last right-click, offered as "Copy". */
  contextCell: string;
  actions: KebabAction[];
  children: React.ReactNode;
}>) {
  return (
    <ContextMenu>
      <ContextMenuTrigger asChild>{children}</ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        {contextCell ? (
          <ContextMenuItem className="gap-2" onSelect={() => void navigator.clipboard.writeText(contextCell)}>
            <Copy aria-hidden className="size-3.5" />
            <span className="truncate">Copy “{contextCell}”</span>
          </ContextMenuItem>
        ) : null}
        <ContextMenuItem
          className="gap-2"
          onSelect={() =>
            // Tab-separated in the visible column order, so it pastes into a spreadsheet as one row.
            void navigator.clipboard.writeText(
              cells.filter((cell) => cell.column.id !== ADMIN_ACTION_COLUMN_ID).map((cell) => String(cell.getValue() ?? "")).join("\t")
            )
          }
        >
          <Rows3 aria-hidden className="size-3.5" />
          Copy row
        </ContextMenuItem>
        {actions.length > 0 ? <ContextMenuSeparator /> : null}
        {actions.map((action) => {
          const Icon = action.icon;
          const content = (
            <>
              {Icon ? <Icon aria-hidden className="size-3.5" /> : null}
              {action.label}
            </>
          );
          return (
            <ContextMenuItem
              key={action.label}
              asChild={action.href !== undefined}
              onSelect={action.onSelect}
              className={cn("gap-2", action.destructive && "text-danger focus:text-danger")}
            >
              {action.href !== undefined ? <Link href={action.href}>{content}</Link> : content}
            </ContextMenuItem>
          );
        })}
      </ContextMenuContent>
    </ContextMenu>
  );
}
