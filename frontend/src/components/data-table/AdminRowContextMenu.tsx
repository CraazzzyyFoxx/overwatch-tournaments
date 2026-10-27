"use client";

import React, { useState } from "react";
import { useTranslations } from "next-intl";
import type { Row, Table } from "@tanstack/react-table";
import { Copy, Rows3 } from "lucide-react";

import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { Link } from "@/components/data-table/host";
import { ADMIN_ACTION_COLUMN_ID } from "@/components/data-table/columns";
import type { KebabAction } from "@/components/data-table/kebab-column";

interface MenuState {
  /** Row under the last right-click or touch press; null when that was not on a row. */
  rowId: string | null;
  /** Text of the cell under it, offered as "Copy". */
  cellText: string;
  open: boolean;
}

/**
 * Right-click / long-press menu on the rows: the cell under the pointer, the
 * row as a spreadsheet line, and whatever the kebab column offers.
 *
 * One per table, triggered by `children` (the `<tbody>`). The row is found
 * from the event and its items are built when the menu opens, so neither
 * opening it nor the state it keeps repaints a row.
 */
export function AdminRowContextMenu<TData>({
  table,
  rowActions,
  children
}: Readonly<{
  table: Table<TData>;
  /** The kebab column's actions, when the screen has one. */
  rowActions?: (row: TData) => KebabAction[];
  children: React.ReactNode;
}>) {
  const [menu, setMenu] = useState<MenuState>({ rowId: null, cellText: "", open: false });
  const aim = (event: React.SyntheticEvent) => {
    const target = event.target as HTMLElement;
    const rowId = target.closest<HTMLElement>("tr[data-row-id]")?.dataset.rowId ?? null;
    const cellText = target.closest("td")?.textContent.trim() ?? "";
    setMenu((current) => ({ ...current, rowId, cellText }));
  };
  const row = menu.rowId === null ? undefined : table.getRowModel().rowsById[menu.rowId];

  return (
    <ContextMenu
      open={menu.open}
      // Radix opens on a right-click or long-press anywhere in the body; only a row has a menu.
      onOpenChange={(open) => setMenu((current) => ({ ...current, open: open && current.rowId !== null }))}
    >
      <ContextMenuTrigger
        asChild
        onContextMenu={aim}
        // A long-press opens from a timer this press starts, with no `contextmenu` to aim by.
        onPointerDown={(event) => { if (event.pointerType !== "mouse") aim(event); }}
      >
        {children}
      </ContextMenuTrigger>
      <ContextMenuContent className="w-56">
        {row ? <RowMenuItems row={row} cellText={menu.cellText} rowActions={rowActions} /> : null}
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** Mounted only while the menu is open, so the kebab's actions are asked for then and not on every table render. */
function RowMenuItems<TData>({
  row,
  cellText,
  rowActions
}: Readonly<{ row: Row<TData>; cellText: string; rowActions?: (row: TData) => KebabAction[] }>) {
  const t = useTranslations("kitTable.table");
  const actions = rowActions?.(row.original).filter((action) => !action.hidden) ?? [];
  return (
    <>
      {cellText ? (
        <ContextMenuItem className="gap-2" onSelect={() => void navigator.clipboard.writeText(cellText)}>
          <Copy aria-hidden className="size-3.5" />
          <span className="truncate">{t("copy", { value: cellText })}</span>
        </ContextMenuItem>
      ) : null}
      <ContextMenuItem
        className="gap-2"
        onSelect={() =>
          // Tab-separated in the visible column order, so it pastes into a spreadsheet as one row.
          void navigator.clipboard.writeText(
            row
              .getVisibleCells()
              .filter((cell) => cell.column.id !== ADMIN_ACTION_COLUMN_ID)
              .map((cell) => String(cell.getValue() ?? ""))
              .join("\t")
          )
        }
      >
        <Rows3 aria-hidden className="size-3.5" />
        {t("copyRow")}
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
            variant={action.destructive ? "destructive" : "default"}
          >
            {action.href !== undefined ? <Link href={action.href}>{content}</Link> : content}
          </ContextMenuItem>
        );
      })}
    </>
  );
}
