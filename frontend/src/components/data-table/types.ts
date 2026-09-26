import type React from "react";
import type { ColumnDef, Row } from "@tanstack/react-table";

import type { AdminTableFilters } from "@/components/data-table/filters";

/** One page of a server-mode query. Structurally matches the API's paginated envelope. */
export interface PaginatedResponse<T> {
  page: number;
  per_page: number;
  total: number;
  results: T[];
}

export type SortDir = "asc" | "desc";

/** `aria-sort` for a sortable header from TanStack's `getIsSorted()`; non-sortable headers omit the attribute. */
export function ariaSortValue(direction: "asc" | "desc" | false): "ascending" | "descending" | "none" {
  if (direction === "asc") return "ascending";
  if (direction === "desc") return "descending";
  return "none";
}

export interface DataTableGroup<TData> {
  key: string;
  label: React.ReactNode;
  rows: Row<TData>[];
}

export interface DataTableProps<TData> {
  /**
   * Server mode: one page per request. Mutually exclusive with `rows` — the
   * table pages, sorts and filters on the server and the caller turns the
   * table's state into query params.
   */
  queryKey?: (page: number, search: string, pageSize: number, sortField: string | null, sortDir: SortDir, filters: AdminTableFilters) => readonly unknown[];
  queryFn?: (page: number, search: string, pageSize: number, sortField: string | null, sortDir: SortDir, filters: AdminTableFilters) => Promise<PaginatedResponse<TData>>;

  /** Sort applied until the user picks another, e.g. newest submission first. */
  initialSort?: { field: string; dir: SortDir };

  /**
   * Client mode: every row already in memory, so search, sort, header filters
   * and paging run locally. For pools small enough to fetch whole (a
   * tournament's registrations) this removes a refetch per interaction.
   */
  rows?: TData[];
  /** Client mode only: the caller's own fetch is still in flight. */
  isLoading?: boolean;

  columns: ColumnDef<TData>[];
  /**
   * Label and placeholder for the built-in search box. Omit it together with
   * a `toolbar` that carries its own search, and this one is not rendered —
   * two search fields over one table is the bug, not the feature.
   */
  searchPlaceholder?: string;
  emptyMessage?: string;
  initialPageSize?: number;
  pageSizeOptions?: number[];

  /**
   * `pages` (default) numbers the results. `infinite` grows one batch at a
   * time from a sentinel plus a Load-more button, and `all` renders every row
   * with no footer at all; both are client mode only — server mode would need
   * an accumulating `useInfiniteQuery` contract.
   * `initialPageSize` is the batch size for `pages`/`infinite`, and `?page=`
   * still records how deep the list is, so a reload restores the same depth.
   */
  paging?: "pages" | "infinite" | "all";
  /** Plural noun for the rows in the infinite footer, e.g. "registrations". */
  rowUnit?: string;

  /**
   * Vertical alignment of body cells. `middle` (default) centres one-line rows;
   * `top` is for tables whose cells wrap to different heights (role chips next
   * to a single badge), where centring leaves the short cells floating.
   */
  cellAlign?: "top" | "middle";

  /**
   * Opaque identity of filters the caller owns (chips, scope selects) rather
   * than this table. Changing it resets to page 1: narrowing a filter while on
   * page 4 otherwise lands on a page the new result set does not have.
   */
  filterKey?: string;

  /**
   * The column-declared filter set (`meta.filter`), which the table applies to
   * the query in server mode and to the rows in client mode, and mirrors into
   * the URL under each spec's own param name.
   *
   * Pass both to let `kit/FilterBar` own the state: the chips write the
   * URL, this reads it. Uncontrolled otherwise — there is no filter control
   * in the header any more, so the only writers left are a deep link, a
   * back/forward, and the empty state's "Clear filters".
   */
  filters?: AdminTableFilters;
  onFiltersChange?: (next: AdminTableFilters) => void;

  /** Stable row identity — required for selection and expansion to survive a refetch. */
  getRowId?: (row: TData) => string;

  /**
   * Adds the leading checkbox column. Returning false makes a row unselectable
   * (its checkbox is not rendered and select-all skips it).
   */
  enableRowSelection?: (row: Row<TData>) => boolean;
  /** Rendered in the toolbar while at least one row is selected. */
  bulkActions?: (selected: TData[], clearSelection: () => void) => React.ReactNode;

  /** Detail panel revealed by the leading chevron. */
  renderExpanded?: (row: Row<TData>) => React.ReactNode;

  /**
   * Splits the current page into labelled groups, each preceded by a header
   * row. Receives the rows in display order and must return all of them.
   */
  groupRows?: (rows: Row<TData>[]) => DataTableGroup<TData>[];

  /**
   * Shows the "Columns" picker and persists visibility under this
   * localStorage key. Only columns declaring `meta.category` are offered.
   */
  columnsStorageKey?: string;

  onRowClick?: (row: Row<TData>) => void;
  onRowDoubleClick?: (row: Row<TData>) => void;
  actions?: React.ReactNode;

  /**
   * Rendered in its own row above the table: this is where `FilterBar`
   * goes. Unlike `actions` (a cluster to the right of the search box) it owns
   * the full width, because a chip row wraps.
   */
  toolbar?: React.ReactNode;

  /**
   * Row currently open in the inspector (`?id=`). That row is marked
   * `aria-current="true"` and tinted.
   *
   * NOT `aria-selected`: inside `role="table"` that attribute is not allowed
   * on a row (only `grid`/`treegrid` support it), so it would be an ARIA
   * violation rather than a state announcement. `aria-current` is the
   * "current item in a set" primitive and is valid on any element.
   */
  inspectorId?: string | null;

  /**
   * Below `md` the table becomes a list of cards. Without this, a card shows
   * the first three visible columns; pass it when those three are the wrong
   * three (F18 ·1).
   */
  renderMobileCard?: (row: Row<TData>) => React.ReactNode;
}
