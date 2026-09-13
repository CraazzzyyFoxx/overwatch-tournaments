"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, type LucideIcon } from "lucide-react";
import Link from "next/link";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { adminColumnMeta } from "@/components/admin/admin-table-columns";
import { cn } from "@/lib/utils";

export interface KebabAction {
  label: string;
  icon?: LucideIcon;
  /** Omitted for a pure `href` item. */
  onSelect?: () => void;
  destructive?: boolean;
  /** A permission-gated action is absent, never disabled. */
  hidden?: boolean;
  href?: string;
}

export interface KebabColumnOptions<T> {
  /**
   * Names the row in the trigger's accessible name. Without it every row's
   * menu button reads the same, so a screen-reader user hears "Actions for
   * row" nine times with nothing telling them apart.
   */
  rowLabel?: (row: T) => string;
}

/**
 * The single row-actions convention for the admin panel: one always-visible
 * `⋯` menu.
 *
 * It replaced two competing conventions — an edit-pencil/delete-trash pair
 * and a catalogue dropdown, each with its own permission gating —
 * and it is always visible: the old actions column was `opacity-0` until
 * hover, which made every list screen's primary actions undiscoverable
 * without a mouse.
 */
export function createKebabColumn<T>(
  items: (row: T) => KebabAction[],
  options?: KebabColumnOptions<T>
): ColumnDef<T> {
  return {
    id: "actions",
    header: () => <span className="sr-only">Actions</span>,
    enableSorting: false,
    size: 56,
    meta: adminColumnMeta<T>({ align: "right", rowActions: items }),
    cell: ({ row }) => {
      const actions = items(row.original).filter((action) => !action.hidden);
      if (actions.length === 0) return null;

      const label = options?.rowLabel?.(row.original) ?? `row ${row.id}`;

      return (
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={`Actions for ${label}`}
            className={cn(
              "inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors",
              "hover:bg-accent/40 hover:text-foreground",
              "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            )}
          >
            <MoreHorizontal aria-hidden className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-48">
            {actions.map((action) => {
              const Icon = action.icon;
              const content = (
                <>
                  {Icon ? <Icon aria-hidden className="size-3.5" /> : null}
                  {action.label}
                </>
              );

              return (
                <DropdownMenuItem
                  key={action.label}
                  asChild={action.href !== undefined}
                  onSelect={action.onSelect}
                  className={cn("gap-2", action.destructive && "text-danger focus:text-danger")}
                >
                  {action.href !== undefined ? (
                    <Link href={action.href}>{content}</Link>
                  ) : (
                    content
                  )}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      );
    }
  };
}
