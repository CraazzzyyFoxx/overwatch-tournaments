import type React from "react";
import type { ColumnDef, Row } from "@tanstack/react-table";
import type { LucideIcon } from "lucide-react";

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

/**
 * A screen's command over its list — create, sync, upload, open a tool. Never a
 * filter or a way of looking at the rows: those are the `toolbar`'s and the
 * "View" menu's. The table lays commands out itself: outline buttons with the
 * one `primary` last, and on a narrow table the secondary ones fold into the
 * "View" menu while the primary stays as its icon.
 */
export interface TableCommand {
  /** Stable key among the table's commands. */
  id: string;
  label: string;
  /** Required for a `primary` that should shrink to an icon on a narrow table; without one it keeps its label. */
  icon?: LucideIcon;
  /** Omitted for a pure `href` command. */
  onSelect?: () => void;
  href?: string;
  /** The filled button, last in the row. At most one per table. */
  primary?: boolean;
  /** A permission the reader lacks: the command is absent, never disabled (DESIGN §14). */
  hidden?: boolean;
  /** In flight: a spinner stands in for the icon. Whether it can be pressed again is `disabled`'s call. */
  pending?: boolean;
  disabled?: boolean;
  /** Disabled until something else is true, saying what: shown as text beside the command, not only as a tooltip. */
  disabledReason?: string;
}

/** The reader's grouping choice, offered in the table's "View" menu; `groupRows` does the grouping. */
export interface DataTableGroupBy {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
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
   * a `toolbar` and no search box is rendered: a screen whose server does not
   * search must not offer a field that does nothing.
   */
  searchPlaceholder?: string;
  emptyMessage?: string;
  /**
   * Rows per page. Omit it on a `pages` table to fit the page to the viewport
   * ("Auto" in the rows-per-page list); the phone's card list then gets 15.
   */
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
  /** Translated plural noun for the rows in the infinite footer; the footer's own "rows" by default. */
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
  /**
   * The buttons acting on the selected rows. The table shows them in its
   * floating selection bar, with the count (off-page rows included) and a way
   * to clear it; the toolbar never changes with the selection.
   */
  bulkActions?: (selected: TData[], clearSelection: () => void) => React.ReactNode;

  /** Detail panel revealed by the leading chevron. */
  renderExpanded?: (row: Row<TData>) => React.ReactNode;

  /**
   * Splits the current page into labelled groups, each preceded by a header
   * row. Receives the rows in display order and must return all of them.
   */
  groupRows?: (rows: Row<TData>[]) => DataTableGroup<TData>[];
  groupBy?: DataTableGroupBy;

  /**
   * Offers "Columns" in the "View" menu and persists visibility under this
   * localStorage key. Only columns declaring `meta.category` are offered.
   */
  columnsStorageKey?: string;

  onRowClick?: (row: Row<TData>) => void;
  onRowDoubleClick?: (row: Row<TData>) => void;
  /** The screen's commands over the list; see `TableCommand`. */
  commands?: TableCommand[];

  /**
   * The screen's `FilterBar`, after the search box. On a narrow table its
   * "+ Filter" turns into an icon beside the search and its chips take a row
   * of their own, only while there are any.
   */
  toolbar?: React.ReactNode;

  /** A line about the whole list — a total, an average — at the table's foot. */
  summary?: React.ReactNode;

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
   * Server mode: the rows of the page on screen, whenever they change —
   * including a page served from the query cache, where `queryFn` never runs.
   * This is how a screen keeps an inspector in step with the table: reading
   * the rows inside `queryFn` instead goes stale the moment a cached page is
   * shown again, and the open row is then "not on this page". The whole
   * response comes along too, for `total` and any extras the screen reads.
   */
  onPageRowsChange?: (rows: TData[], page: PaginatedResponse<TData>) => void;

  /**
   * Below `md` the table becomes a list of cards. Without this, a card shows
   * the first three visible columns; pass it when those three are the wrong
   * three (F18 ·1).
   */
  renderMobileCard?: (row: Row<TData>) => React.ReactNode;

  /**
   * `false` when the table is the body of a card that already frames it (a
   * hub's `SettingGroup flush`): no border, fill or corners of its own, so it
   * is not a card inside a card.
   */
  framed?: boolean;
}
