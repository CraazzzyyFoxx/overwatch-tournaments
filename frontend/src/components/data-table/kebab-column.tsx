"use client";

import type { ColumnDef } from "@tanstack/react-table";
import { MoreHorizontal, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Link } from "@/components/data-table/host";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger
} from "@/components/ui/dropdown-menu";
import { columnMeta } from "@/components/data-table/columns";

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

interface KebabColumnOptions<T> {
  /**
   * Names the row in the trigger's accessible name. Without it every row's
   * menu button reads the same, so a screen-reader user hears "Actions for
   * row" nine times with nothing telling them apart.
   */
  rowLabel?: (row: T) => string;
}

function KebabCell({ actions, label, rowId }: Readonly<{ actions: KebabAction[]; label?: string; rowId: string }>) {
  const t = useTranslations("kitTable.dataTableExtra");
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={t("actionsFor", { label: label ?? t("rowFallback", { id: rowId }) })}
          className="text-muted-foreground"
        >
          <MoreHorizontal aria-hidden />
        </Button>
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
              variant={action.destructive ? "destructive" : "default"}
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

function KebabHeader() {
  const t = useTranslations("kitTable.dataTableExtra");
  return <span className="sr-only">{t("actions")}</span>;
}

/**
 * The single row-actions convention for the admin panel: one always-visible
 * `⋯` menu.
 *
 * It replaced two competing conventions — an edit-pencil/delete-trash pair
 * and a catalogue dropdown, each with its own permission gating.
 */
export function createKebabColumn<T>(
  items: (row: T) => KebabAction[],
  options?: KebabColumnOptions<T>
): ColumnDef<T> {
  return {
    id: "actions",
    header: () => <KebabHeader />,
    enableSorting: false,
    enableResizing: false,
    size: 56,
    meta: columnMeta<T>({ align: "right", rowActions: items }),
    cell: ({ row }) => {
      const actions = items(row.original).filter((action) => !action.hidden);
      if (actions.length === 0) return null;

      return <KebabCell actions={actions} label={options?.rowLabel?.(row.original)} rowId={row.id} />;
    }
  };
}
