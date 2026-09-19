import type { ColumnMeta } from "@tanstack/react-table";

import type { AdminColumnFilterSpec } from "@/components/data-table/filters";
import type { KebabAction } from "@/components/data-table/kebab-column";

/** Breakpoint below which a column is hidden entirely. */
export type AdminColumnResponsive = "always" | "sm" | "md" | "lg";

/** Column category, used to group the "Columns" picker. */
export type AdminColumnCategory = "core" | "meta" | "admin";

/** Column metadata `AdminDataTable` understands. */
export interface AdminColumnMeta<TData = unknown> {
  /** Column filter contract for `kit/AdminFilterBar` and the table's engine. */
  filter?: AdminColumnFilterSpec;
  /** Picker group. Columns without one are not offered for hiding. */
  category?: AdminColumnCategory;
  /** Hidden until the user turns it on in the picker. */
  defaultHidden?: boolean;
  /** Never hideable — rendered checked and disabled in the picker. */
  mandatory?: boolean;
  responsive?: AdminColumnResponsive;
  /**
   * Pin this column to the left edge while the table scrolls sideways. Only a
   * left-edge prefix of the visible columns can be pinned, and every pinned
   * column but the first must declare `size` — the offsets are arithmetic, not
   * measured.
   */
  sticky?: boolean;
  align?: "left" | "center" | "right";
  /** Extra classes for this column's `<th>` and `<td>`s (widths, min-widths). */
  className?: string;
  /**
   * Text this column contributes to the toolbar search in client mode. Absent
   * means the column is not searchable — a cell of badges has no useful text.
   */
  searchValue?: (row: TData) => string | null | undefined;
  /** Numeric cells: `tabular-nums` so digits stop jittering between renders. */
  numeric?: boolean;
  /**
   * Row actions, set by `createKebabColumn`. The table mirrors them into a
   * right-click / long-press context menu on the row.
   */
  rowActions?: (row: TData) => KebabAction[];
}

/**
 * TanStack ships `ColumnMeta` as an empty interface, so a plain object literal
 * trips the excess-property check. Cast once, here, instead of scattering casts
 * through every admin column definition.
 */
export const adminColumnMeta = <TData,>(meta: AdminColumnMeta<TData>) =>
  meta as ColumnMeta<TData, unknown>;

export function readAdminColumnMeta<TData>(meta: unknown): AdminColumnMeta<TData> {
  return (meta ?? {}) as AdminColumnMeta<TData>;
}

export const RESPONSIVE_CLASS: Record<AdminColumnResponsive, string> = {
  always: "",
  sm: "hidden sm:table-cell",
  md: "hidden md:table-cell",
  lg: "hidden lg:table-cell"
};

export const ALIGN_CLASS: Record<"left" | "center" | "right", string> = {
  left: "text-left",
  center: "text-center",
  right: "text-right"
};

export const ALIGN_FLEX_CLASS: Record<"left" | "center" | "right", string> = {
  left: "justify-start",
  center: "justify-center",
  right: "justify-end"
};
