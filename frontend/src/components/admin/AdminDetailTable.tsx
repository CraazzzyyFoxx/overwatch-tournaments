"use client";

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Shared class sets for the small hand-built `<Table>`s that live INSIDE
 * another surface: the roster grid in `teams/TeamRosterEditor`, the team
 * list in the tournament hub's Teams tab and the round schedule.
 *
 * Deliberately kept after the redesign, unlike the primitives P6 removed.
 * These are not browsers: they have no search, no paging, no sort, no URL
 * state and no row actions, and each row is an inline editor rather than a
 * link to one. `DataTable` (T2) would add a toolbar, a pager and a URL
 * contract to a nine-row grid nested in a form — and two of those, on the
 * same screen as the real table, would compete for `?page=` and `?sort=`.
 * What those grids actually shared was styling, which is all this file is.
 * Row hover and the head's voice are `ui/table`'s own.
 *
 * Reach for `DataTable` for anything that is the subject of its screen;
 * reach for these styles only for a dense table nested in an editor.
 */

const CELL = "py-2 text-sm first:pl-3 last:pr-3 align-middle";

export const adminDetailTableStyles = {
  shell: "overflow-hidden rounded-lg border border-border/40",
  head: "sticky top-0 z-10 h-8 bg-muted/20 first:pl-3 last:pr-3",
  row: "border-border/30",
  cell: CELL,
  /** `cell` plus `tabular-nums`, so numeric columns line up. */
  numericCell: `${CELL} tabular-nums`
};

interface AdminDetailTableShellProps {
  children: ReactNode;
  className?: string;
}

export function AdminDetailTableShell({ children, className }: Readonly<AdminDetailTableShellProps>) {
  return <div className={cn(adminDetailTableStyles.shell, className)}>{children}</div>;
}
