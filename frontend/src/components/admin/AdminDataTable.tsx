"use client";

import React, { Fragment, useEffect, useId, useRef, useState } from "react";
import {
  ColumnDef,
  ColumnFiltersState,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  Row,
  RowSelectionState,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight, CircleMinus, LoaderCircle, Search } from "lucide-react";
import { usePathname } from "next/navigation";
import { useDebounce } from "use-debounce";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { PaginatedResponse } from "@/types/pagination.types";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { ariaSortValue, cn } from "@/lib/utils";
import {
  collectFilterSpecs,
  parseFiltersFromParams,
  readAdminColumnFilter,
  serializeFilters,
  writeFiltersToParams,
  type AdminTableFilters
} from "@/components/admin/admin-table-filters";
import {
  ALIGN_CLASS,
  ALIGN_FLEX_CLASS,
  RESPONSIVE_CLASS,
  readAdminColumnMeta,
  type AdminColumnCategory
} from "@/components/admin/admin-table-columns";
import { CategorizedColumnPicker } from "@/components/ui/categorized-column-picker";
import { Checkbox } from "@/components/ui/checkbox";
import { InfiniteScrollFooter } from "@/components/ui/infinite-scroll";
import { useColumnVisibility } from "@/hooks/useColumnVisibility";
import { useIsMobile } from "@/hooks/use-mobile";
import { useDragRowSelect } from "@/components/admin/useDragRowSelect";
import { EYEBROW_CLASS } from "@/components/admin/tone";

const ADMIN_ACTION_COLUMN_ID = "actions";
const ADMIN_ACTION_COLUMN_MIN_WIDTH = 80;
/** Width of the select/expand column — keep in sync with its `w-10` class. */
const ADMIN_LEADING_COLUMN_WIDTH = 40;
const DEFAULT_PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100];
const COLUMN_CATEGORY_LABELS: Record<AdminColumnCategory, string> = {
  core: "Core",
  meta: "Meta",
  admin: "Admin"
};

function parsePositiveInt(value: string | null, fallback: number) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function parseSortDir(value: string | null): SortDir {
  return value === "desc" ? "desc" : "asc";
}

/**
 * The id TanStack will give a column definition, before a table exists to ask.
 * Accessor columns fall back to their key; anything else must declare an `id`.
 */
function columnDefId<TData>(column: ColumnDef<TData>): string {
  if (column.id) return column.id;
  return "accessorKey" in column && typeof column.accessorKey === "string" ? column.accessorKey : "";
}

export type SortDir = "asc" | "desc";

export interface AdminDataTableGroup<TData> {
  key: string;
  label: React.ReactNode;
  rows: Row<TData>[];
}

export interface AdminDataTableProps<TData> {
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
   * time from a sentinel plus a Load-more button, and is client mode only —
   * server mode would need an accumulating `useInfiniteQuery` contract.
   * `initialPageSize` is the batch size either way, and `?page=` still records
   * how deep the list is, so a reload restores the same depth.
   */
  paging?: "pages" | "infinite";
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
   * Pass both to let `kit/AdminFilterBar` own the state: the chips write the
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
  groupRows?: (rows: Row<TData>[]) => AdminDataTableGroup<TData>[];

  /**
   * Shows the "Columns" picker and persists visibility under this
   * localStorage key. Only columns declaring `meta.category` are offered.
   */
  columnsStorageKey?: string;

  onRowClick?: (row: Row<TData>) => void;
  onRowDoubleClick?: (row: Row<TData>) => void;
  actions?: React.ReactNode;

  /**
   * Rendered in its own row above the table: this is where `AdminFilterBar`
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

export function AdminDataTable<TData>({
  queryKey,
  queryFn,
  rows,
  isLoading = false,
  columns,
  searchPlaceholder,
  emptyMessage = "No records to show yet.",
  onRowClick,
  onRowDoubleClick,
  actions,
  initialPageSize = 15,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
  filterKey,
  initialSort,
  filters: controlledFilters,
  onFiltersChange,
  getRowId,
  enableRowSelection,
  bulkActions,
  renderExpanded,
  groupRows,
  columnsStorageKey,
  paging = "pages",
  rowUnit = "rows",
  cellAlign = "middle",
  toolbar,
  inspectorId,
  renderMobileCard,
}: Readonly<AdminDataTableProps<TData>>) {
  const isClientMode = rows !== undefined;
  // Server mode has no accumulating query to grow, so it always paginates.
  const isInfinite = isClientMode && paging === "infinite";
  const pathname = usePathname();
  const isMobile = useIsMobile();
  const searchInputId = useId();
  const rowHintId = useId();
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearchValue] = useDebounce(searchValue, 300);
  const [currentPage, setCurrentPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(initialPageSize);
  const [sorting, setSorting] = useState<SortingState>(
    initialSort ? [{ id: initialSort.field, desc: initialSort.dir === "desc" }] : []
  );
  const [uncontrolledFilters, setUncontrolledFilters] = useState<AdminTableFilters>({});
  const filters = controlledFilters ?? uncontrolledFilters;
  const setFilters = (next: AdminTableFilters) => {
    if (onFiltersChange) onFiltersChange(next);
    if (controlledFilters === undefined) setUncontrolledFilters(next);
  };
  const filterSpecs = collectFilterSpecs(columns);
  // Held in a ref so the popstate/URL effects can read the current specs
  // without re-subscribing every render: `columns` is a fresh array each time.
  const filterSpecsRef = useRef(filterSpecs);
  filterSpecsRef.current = filterSpecs;
  const serializedFilters = serializeFilters(filters);
  const sortField = sorting[0]?.id ?? null;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";
  const previousDebouncedSearchRef = useRef("");
  const previousPageSizeRef = useRef(initialPageSize);
  const previousFilterKeyRef = useRef(filterKey);
  const previousSortRef = useRef<{ field: string | null; dir: SortDir }>({ field: null, dir: "asc" });
  const rowClickTimeoutRef = useRef<number | null>(null);
  const previousFiltersRef = useRef("");
  const previousUrlStateRef = useRef({ page: 1, search: "", pageSize: initialPageSize, sortField: null as string | null, sortDir: "asc" as SortDir, filters: "" });
  /**
   * The filter set the last URL parse asked for, held until state carries it.
   *
   * Filters set from the URL land a render later — and for CONTROLLED filters
   * only once the parent applies them, which a StrictMode remount re-parses in
   * between — so until then the URL-sync effect below would write the stale
   * empty set back over the link that was just opened. That is what silently
   * dropped `?tournament=` (and every other header filter) from every deep
   * link and reload. Only filters get this hold: every other piece of table
   * state lives in this component and is set in the same batch, so it lags by
   * exactly one render and cannot be wedged by a caller.
   */
  const pendingUrlFiltersRef = useRef<string | null>(null);
  const safeCurrentPage = Number.isFinite(currentPage) && currentPage > 0 ? currentPage : 1;
  const safePageSize = Number.isFinite(pageSize) && pageSize > 0 ? pageSize : initialPageSize;

  useEffect(() => {
    setPageSize(initialPageSize);
    previousPageSizeRef.current = initialPageSize;
  }, [initialPageSize]);

  useEffect(() => {
    if (previousDebouncedSearchRef.current !== debouncedSearchValue) {
      previousDebouncedSearchRef.current = debouncedSearchValue;
      setCurrentPage(1);
    }
  }, [debouncedSearchValue]);

  useEffect(() => {
    if (previousPageSizeRef.current !== pageSize) {
      previousPageSizeRef.current = pageSize;
      setCurrentPage(1);
    }
  }, [pageSize]);

  useEffect(() => {
    if (previousFilterKeyRef.current !== filterKey) {
      previousFilterKeyRef.current = filterKey;
      setCurrentPage(1);
    }
  }, [filterKey]);

  useEffect(() => {
    const prev = previousSortRef.current;
    if (prev.field !== sortField || prev.dir !== sortDir) {
      previousSortRef.current = { field: sortField, dir: sortDir };
      setCurrentPage(1);
    }
  }, [sortField, sortDir]);

  useEffect(() => {
    if (previousFiltersRef.current !== serializedFilters) {
      previousFiltersRef.current = serializedFilters;
      setCurrentPage(1);
    }
  }, [serializedFilters]);

  const dataQuery = useQuery({
    queryKey: queryKey
      ? queryKey(safeCurrentPage, debouncedSearchValue, safePageSize, sortField, sortDir, filters)
      : ["admin-data-table", "client-mode"],
    queryFn: queryFn
      ? () => queryFn(safeCurrentPage, debouncedSearchValue, safePageSize, sortField, sortDir, filters)
      : () => Promise.resolve({ results: [] as TData[], total: 0, page: 1, per_page: safePageSize }),
    enabled: !isClientMode,
    placeholderData: (previousData) => previousData,
  });

  // Client mode does its own searching, so the search box narrows the rows
  // here instead of turning into a query param. A column opts in by declaring
  // `meta.searchValue`; a column of badges has no useful text to match.
  const searchableColumns = columns.filter((column) => readAdminColumnMeta<TData>(column.meta).searchValue);
  const clientRows = React.useMemo(() => {
    if (!rows) return [];
    const needle = debouncedSearchValue.trim().toLowerCase();
    if (!needle) return rows;
    return rows.filter((row) =>
      searchableColumns.some((column) => {
        const value = readAdminColumnMeta<TData>(column.meta).searchValue?.(row);
        return value ? value.toLowerCase().includes(needle) : false;
      })
    );
  }, [rows, debouncedSearchValue, columns]);

  const data = dataQuery.data ?? { results: [], total: 0, page: 1, per_page: safePageSize };
  const isRefreshing = isClientMode ? isLoading : dataQuery.isFetching && !dataQuery.isLoading;

  const pickerColumns = columns
    .map((column) => {
      const meta = readAdminColumnMeta<TData>(column.meta);
      return {
        id: columnDefId(column),
        label: column.header as React.ReactNode,
        category: meta.category,
        defaultVisible: !meta.defaultHidden,
        mandatory: meta.mandatory === true
      };
    })
    .filter((column): column is typeof column & { category: AdminColumnCategory } =>
      Boolean(column.id) && column.category !== undefined,
    );
  const { visibility, toggleColumn, resetToDefaults } = useColumnVisibility(
    columnsStorageKey ?? null,
    pickerColumns,
  );

  // Header filters are query params in server mode and TanStack column filters
  // in client mode, keyed by the column that declared them.
  const columnFilters: ColumnFiltersState = isClientMode
    ? columns.flatMap((column) => {
        const spec = readAdminColumnFilter(column.meta);
        if (!spec) return [];
        const values = filters[spec.param];
        if (!values?.length) return [];
        const id = columnDefId(column);
        return id ? [{ id, value: values }] : [];
      })
    : [];

  const [rowSelection, setRowSelection] = useState<RowSelectionState>({});

  // Infinite scrolling renders one page that grows: `page` still counts the
  // batches loaded, so `?page=` restores the same depth after a reload.
  const paginationState = isInfinite
    ? { pageIndex: 0, pageSize: safeCurrentPage * safePageSize }
    : { pageIndex: safeCurrentPage - 1, pageSize: safePageSize };

  const table = useReactTable<TData>({
    data: isClientMode ? clientRows : (data.results ?? []),
    columns,
    getRowId,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: isClientMode ? getFilteredRowModel() : undefined,
    getSortedRowModel: isClientMode ? getSortedRowModel() : undefined,
    getPaginationRowModel: isClientMode ? getPaginationRowModel() : undefined,
    getExpandedRowModel: renderExpanded ? getExpandedRowModel() : undefined,
    getRowCanExpand: renderExpanded ? () => true : undefined,
    enableRowSelection: enableRowSelection,
    onSortingChange: setSorting,
    onRowSelectionChange: setRowSelection,
    // Pagination is controlled by this component's own page state, so TanStack
    // must be told where every page change goes — a controlled `state.pagination`
    // with no handler leaves its internal copy free to drift, and its
    // auto-reset then fights this component's state on every render.
    onPaginationChange: isClientMode
      ? (updater) => {
          const next =
            typeof updater === "function"
              ? updater(paginationState)
              : updater;
          setCurrentPage(next.pageIndex + 1);
          setPageSize(next.pageSize);
        }
      : undefined,
    autoResetPageIndex: false,
    state: {
      sorting,
      rowSelection,
      columnVisibility: visibility,
      ...(isClientMode
        ? { columnFilters, pagination: paginationState }
        : {})
    },
    manualPagination: !isClientMode,
    manualSorting: !isClientMode,
    manualFiltering: !isClientMode,
    rowCount: isClientMode ? undefined : (data.total ?? 0),
  });

  const clientFilteredCount = isClientMode ? table.getFilteredRowModel().rows.length : 0;
  const safeTotal = isClientMode
    ? clientFilteredCount
    : Number.isFinite(data.total)
      ? data.total
      : 0;
  const responsePageSize = !isClientMode && Number.isFinite(data.per_page) ? data.per_page : undefined;
  const effectivePageSize = responsePageSize && responsePageSize > 0 ? responsePageSize : safePageSize;
  const availablePageSizeOptions = Array.from(new Set([...pageSizeOptions, effectivePageSize])).sort((a, b) => a - b);
  const totalPageCount = Math.max(1, Math.ceil(safeTotal / effectivePageSize));
  const rangeStart = safeTotal > 0 ? (safeCurrentPage - 1) * effectivePageSize + 1 : 0;
  const rangeEnd = safeTotal > 0 ? Math.min(safeCurrentPage * effectivePageSize, safeTotal) : 0;
  const selectedRows = table.getSelectedRowModel().rows;
  const dragSelect = useDragRowSelect(table);
  const selectableRows = enableRowSelection
    ? table.getRowModel().rows.filter((row) => row.getCanSelect())
    : [];

  useEffect(() => {
    if (safeCurrentPage > totalPageCount) {
      setCurrentPage(totalPageCount);
    }
  }, [safeCurrentPage, totalPageCount]);

  // Browser back/forward sync
  useEffect(() => {
    const syncStateFromUrl = () => {
      const params = new URLSearchParams(window.location.search);
      const nextPage = parsePositiveInt(params.get("page"), 1);
      const nextSearch = params.get("search") ?? "";
      const nextPageSize = parsePositiveInt(params.get("per_page"), initialPageSize);
      // No `?sort=` yet means the table is still on its default sort, not unsorted.
      const nextSortField = params.get("sort") ?? initialSort?.field ?? null;
      const nextSortDir = params.get("sort")
        ? parseSortDir(params.get("dir"))
        : (initialSort?.dir ?? parseSortDir(params.get("dir")));
      const nextFilters = parseFiltersFromParams(filterSpecsRef.current, params);
      const nextSerializedFilters = serializeFilters(nextFilters);

      previousDebouncedSearchRef.current = nextSearch;
      previousPageSizeRef.current = nextPageSize;
      previousSortRef.current = { field: nextSortField, dir: nextSortDir };
      previousFiltersRef.current = nextSerializedFilters;
      previousUrlStateRef.current = { page: nextPage, search: nextSearch, pageSize: nextPageSize, sortField: nextSortField, sortDir: nextSortDir, filters: nextSerializedFilters };
      pendingUrlFiltersRef.current = nextSerializedFilters;
      setCurrentPage(nextPage);
      setSearchValue(nextSearch);
      setPageSize(nextPageSize);
      setSorting(nextSortField ? [{ id: nextSortField, desc: nextSortDir === "desc" }] : []);
      setFilters(nextFilters);
    };

    syncStateFromUrl();
    window.addEventListener("popstate", syncStateFromUrl);
    return () => window.removeEventListener("popstate", syncStateFromUrl);
  }, [initialPageSize]);

  useEffect(() => {
    return () => {
      if (rowClickTimeoutRef.current !== null) window.clearTimeout(rowClickTimeoutRef.current);
    };
  }, []);

  // URL sync
  useEffect(() => {
    if (pendingUrlFiltersRef.current !== null) {
      if (pendingUrlFiltersRef.current !== serializedFilters) return;
      pendingUrlFiltersRef.current = null;
    }

    const params = new URLSearchParams(window.location.search);
    const prev = previousUrlStateRef.current;
    const searchChanged = prev.search !== debouncedSearchValue;
    const pageChanged = prev.page !== safeCurrentPage;
    const pageSizeChanged = prev.pageSize !== safePageSize;
    const sortFieldChanged = prev.sortField !== sortField;
    const sortDirChanged = prev.sortDir !== sortDir;
    const filtersChanged = prev.filters !== serializedFilters;

    if (!searchChanged && !pageChanged && !pageSizeChanged && !sortFieldChanged && !sortDirChanged && !filtersChanged) return;

    const currentSearch = params.get("search") ?? "";
    const currentPageParam = Number.parseInt(params.get("page") ?? "1", 10) || 1;
    const currentPageSizeParam = parsePositiveInt(params.get("per_page"), initialPageSize);
    const currentSortField = params.get("sort") ?? null;
    const currentSortDir = parseSortDir(params.get("dir"));
    const currentFilters = serializeFilters(parseFiltersFromParams(filterSpecsRef.current, params));

    if (
      currentSearch === debouncedSearchValue &&
      currentPageParam === safeCurrentPage &&
      currentPageSizeParam === safePageSize &&
      currentSortField === sortField &&
      currentSortDir === sortDir &&
      currentFilters === serializedFilters
    ) {
      previousUrlStateRef.current = { page: safeCurrentPage, search: debouncedSearchValue, pageSize: safePageSize, sortField, sortDir, filters: serializedFilters };
      return;
    }

    if (debouncedSearchValue) params.set("search", debouncedSearchValue); else params.delete("search");
    if (safeCurrentPage > 1) params.set("page", String(safeCurrentPage)); else params.delete("page");
    if (safePageSize !== initialPageSize) params.set("per_page", String(safePageSize)); else params.delete("per_page");
    if (sortField) { params.set("sort", sortField); if (sortDir === "desc") params.set("dir", "desc"); else params.delete("dir"); } else { params.delete("sort"); params.delete("dir"); }
    writeFiltersToParams(filterSpecsRef.current, filters, params);

    const query = params.toString();
    const nextUrl = query ? `${pathname}?${query}` : pathname;

    if (searchChanged || pageSizeChanged || sortFieldChanged || sortDirChanged || filtersChanged) {
      window.history.replaceState(null, "", nextUrl);
    } else {
      window.history.pushState(null, "", nextUrl);
    }

    previousUrlStateRef.current = { page: safeCurrentPage, search: debouncedSearchValue, pageSize: safePageSize, sortField, sortDir, filters: serializedFilters };
  }, [safeCurrentPage, debouncedSearchValue, initialPageSize, safePageSize, pathname, sortField, sortDir, filters, serializedFilters]);

  const getColumnStyle = (column: { id: string; getSize: () => number; columnDef: { size?: number } }) => {
    const configuredSize = typeof column.columnDef.size === "number" ? column.getSize() : undefined;
    const width = column.id === ADMIN_ACTION_COLUMN_ID ? Math.max(configuredSize ?? 0, ADMIN_ACTION_COLUMN_MIN_WIDTH) : configuredSize;
    return width ? { width, minWidth: width } : undefined;
  };

  const hasRowAction = Boolean(onRowClick || onRowDoubleClick);

  const isInteractiveRowTarget = (target: HTMLElement) => {
    return Boolean(target.closest("button, a, input, select, textarea, [role='button'], [role='link'], [data-radix-collection-item]"));
  };

  const handleRowClick = (event: React.MouseEvent<HTMLTableRowElement>, row: Row<TData>) => {
    if (!onRowClick) return;
    if (isInteractiveRowTarget(event.target as HTMLElement)) return;

    if (onRowDoubleClick) {
      if (rowClickTimeoutRef.current !== null) window.clearTimeout(rowClickTimeoutRef.current);
      rowClickTimeoutRef.current = window.setTimeout(() => { onRowClick(row); rowClickTimeoutRef.current = null; }, 200);
      return;
    }
    onRowClick(row);
  };

  const handleRowDoubleClick = (event: React.MouseEvent<HTMLTableRowElement>, row: Row<TData>) => {
    if (!onRowDoubleClick) return;
    if (isInteractiveRowTarget(event.target as HTMLElement)) return;
    if (rowClickTimeoutRef.current !== null) { window.clearTimeout(rowClickTimeoutRef.current); rowClickTimeoutRef.current = null; }
    onRowDoubleClick(row);
  };

  const handlePageSizeChange = (nextPageSize: number) => {
    setCurrentPage(1);
    setPageSize(nextPageSize);
  };

  const handleRowKeyDown = (event: React.KeyboardEvent<HTMLTableRowElement>, row: Row<TData>) => {
    if (!onRowClick) return;
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onRowClick(row); }
  };

  const hasLeadingColumn = Boolean(enableRowSelection || renderExpanded);
  const leadingColumnCount = hasLeadingColumn ? 1 : 0;
  const bodyColumnCount = table.getVisibleLeafColumns().length + leadingColumnCount;

  // Sticky pins a left-edge PREFIX of the visible columns: a pinned column with
  // scrolling ones in front of it would park itself over the wrong neighbours.
  // Offsets are summed from declared sizes rather than measured, so every
  // pinned column after the first must set `size`.
  const stickyLeft = new Map<string, number>();
  let stickyOffset = hasLeadingColumn ? ADMIN_LEADING_COLUMN_WIDTH : 0;
  for (const column of table.getVisibleLeafColumns()) {
    if (!readAdminColumnMeta<TData>(column.columnDef.meta).sticky) break;
    stickyLeft.set(column.id, stickyOffset);
    stickyOffset += typeof column.columnDef.size === "number" ? column.getSize() : 0;
  }
  const lastStickyId = [...stickyLeft.keys()].pop() ?? null;

  /** Sticky class + `left` for a data cell, or nothing when it is not pinned. */
  const stickyCell = (columnId: string, style?: React.CSSProperties) => {
    const left = stickyLeft.get(columnId);
    if (left === undefined) return { className: undefined, style };
    return {
      className: cn("admin-sticky-col", columnId === lastStickyId && "admin-sticky-col-edge"),
      style: { ...style, left }
    };
  };
  const pageRows = table.getRowModel().rows;
  const rowGroups = groupRows
    ? groupRows(pageRows)
    : [{ key: "all", label: null, rows: pageRows }];

  const renderLeadingCell = (row: Row<TData>) => (
    <TableCell
      className={cn(
        "w-10 py-2.5 pl-4",
        cellAlign === "top" ? "align-top" : "align-middle",
        stickyLeft.size > 0 && "admin-sticky-col"
      )}
      style={stickyLeft.size > 0 ? { left: 0 } : undefined}
    >
      <div className="flex items-center gap-1.5">
        {renderExpanded ? (
          <button
            type="button"
            onClick={row.getToggleExpandedHandler()}
            aria-expanded={row.getIsExpanded()}
            aria-label={row.getIsExpanded() ? "Collapse details" : "Expand details"}
            className="flex size-5 shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-accent/30 hover:text-foreground"
          >
            {row.getIsExpanded() ? (
              <ChevronDown aria-hidden className="size-4" />
            ) : (
              <ChevronRight aria-hidden className="size-4" />
            )}
          </button>
        ) : null}
        {enableRowSelection && row.getCanSelect() ? (
          <Checkbox
            checked={row.getIsSelected()}
            onCheckedChange={(checked) => row.toggleSelected(checked === true)}
            onPointerDown={dragSelect.checkboxPointerDown(row)}
            onClick={dragSelect.checkboxClick}
            className="touch-none"
            aria-label={`Select row ${row.id}`}
          />
        ) : null}
      </div>
    </TableCell>
  );

  /**
   * The built-in search box stays unless a `toolbar` was handed in without a
   * `searchPlaceholder` — that is the screen saying "my filter bar owns the
   * search". Passing both keeps the table's own box, for a toolbar that is
   * only chips.
   */
  const showSearch = searchPlaceholder !== undefined || toolbar === undefined;
  const searchLabel = searchPlaceholder ?? "Search…";
  const hasToolbarTrailing =
    Boolean(actions) ||
    Boolean(columnsStorageKey) ||
    isRefreshing ||
    Boolean(bulkActions && selectedRows.length > 0);

  const emptyState = (
    <div className="flex flex-col items-center justify-center gap-2">
      <CircleMinus aria-hidden className="size-5 text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">{emptyMessage}</p>
      {searchValue || serializedFilters ? (
        <>
          <p className="text-xs text-muted-foreground">
            Nothing matches the current {searchValue && serializedFilters ? "search and filters" : searchValue ? "search" : "filters"}.
          </p>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => { setSearchValue(""); setFilters({}); }}
          >
            {searchValue && serializedFilters ? "Clear search and filters" : searchValue ? "Clear search" : "Clear filters"}
          </Button>
        </>
      ) : null}
    </div>
  );

  /**
   * Below `md` a wide table either scrolls sideways past the point of use or
   * hides its columns, so the rows become cards instead (F18 ·1). Three
   * columns is what fits a phone row; a screen whose three most important
   * columns are not the first three passes `renderMobileCard`.
   */
  const mobileCardColumns = table
    .getVisibleLeafColumns()
    .filter((column) => column.id !== ADMIN_ACTION_COLUMN_ID)
    .slice(0, 3);

  const renderMobileRow = (row: Row<TData>) => {
    const cells = row.getVisibleCells();
    const actionCell = cells.find((cell) => cell.column.id === ADMIN_ACTION_COLUMN_ID);
    const body = renderMobileCard ? (
      renderMobileCard(row)
    ) : (
      <>
        {mobileCardColumns.map((column) => {
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
          "flex items-start gap-2 border-b border-border/30 px-4 py-3 last:border-b-0",
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
  };

  return (
    <div className="rounded-xl border border-border/50 bg-card/50 overflow-hidden">
      {/* ── TOOLBAR ─────────────────────────────────────── */}
      {/* One row: search, then the screen's filter bar (chips wrap inside it),
          then the table's own controls. Two stacked rows cost a full band of
          chrome for a chip row that is empty most of the time. */}
      {toolbar || showSearch || hasToolbarTrailing ? (
        <div className="flex flex-wrap items-center gap-3 border-b border-border/40 px-4 py-2.5">
          {showSearch ? (
            <div className="relative w-64 shrink-0">
              <Label htmlFor={searchInputId} className="sr-only">{searchLabel}</Label>
              <Search aria-hidden className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                id={searchInputId}
                autoComplete="off"
                className="h-8 border-border bg-muted/30 pl-9 text-sm placeholder:text-muted-foreground focus-visible:ring-1 focus-visible:ring-ring focus-visible:border-ring"
                name="admin-table-search"
                placeholder={searchLabel}
                value={searchValue}
                onChange={(event) => setSearchValue(event.target.value)}
              />
            </div>
          ) : null}

          {toolbar ? <div className="min-w-0 flex-1">{toolbar}</div> : null}

          {isRefreshing ? (
            <output className="flex shrink-0 items-center text-muted-foreground">
              <LoaderCircle aria-hidden className="size-3 animate-spin" />
              <span className="sr-only">Refreshing results…</span>
            </output>
          ) : null}

          <div className="ml-auto flex shrink-0 items-center gap-2">
            {bulkActions && selectedRows.length > 0
              ? bulkActions(
                  selectedRows.map((row) => row.original),
                  () => setRowSelection({})
                )
              : null}
            {columnsStorageKey ? (
              <CategorizedColumnPicker<AdminColumnCategory, (typeof pickerColumns)[number]>
                columns={pickerColumns}
                categories={["core", "meta", "admin"]}
                categoryLabel={(category) => COLUMN_CATEGORY_LABELS[category]}
                visibility={visibility}
                onToggle={toggleColumn}
                onReset={resetToDefaults}
                triggerLabel="Columns"
                resetLabel="Reset to defaults"
                isMandatory={(id) => pickerColumns.some((column) => column.id === id && column.mandatory)}
              />
            ) : null}
            {actions}
          </div>
        </div>
      ) : null}

      {/* ── TABLE ───────────────────────────────────────── */}
      <div className="overflow-x-auto">
        {onRowClick ? (
          <p id={rowHintId} className="sr-only">
            Press Enter to open the focused row.
          </p>
        ) : null}
        {isMobile ? (
          pageRows.length > 0 ? (
            <ul aria-label="Rows">{rowGroups.flatMap((group) => group.rows).map(renderMobileRow)}</ul>
          ) : (
            <div className="py-8 text-center">{emptyState}</div>
          )
        ) : (
        <Table className="min-w-full border-separate border-spacing-0">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent">
                {hasLeadingColumn ? (
                  <TableHead
                    className={cn(
                      "h-9 w-10 border-b border-border/40 pl-4 text-left",
                      stickyLeft.size > 0 ? "admin-sticky-col" : "bg-muted/20"
                    )}
                    style={stickyLeft.size > 0 ? { left: 0 } : undefined}
                  >
                    {enableRowSelection ? (
                      <Checkbox
                        checked={
                          selectableRows.length > 0 &&
                          selectableRows.every((row) => row.getIsSelected())
                        }
                        disabled={selectableRows.length === 0}
                        onCheckedChange={(checked) =>
                          selectableRows.forEach((row) => row.toggleSelected(checked === true))
                        }
                        aria-label="Select visible selectable rows"
                      />
                    ) : null}
                  </TableHead>
                ) : null}
                {headerGroup.headers.map((header, index) => {
                  const isActionColumn = header.column.id === ADMIN_ACTION_COLUMN_ID;
                  const isFirstColumn = index === 0 && !hasLeadingColumn;
                  const isLastColumn = index === headerGroup.headers.length - 1;
                  const canSort = header.column.getCanSort();
                  const sorted = header.column.getIsSorted();
                  const columnMeta = readAdminColumnMeta<TData>(header.column.columnDef.meta);
                  const align = columnMeta.align ?? (isActionColumn ? "right" : "left");
                  const sticky = stickyCell(header.column.id, getColumnStyle(header.column));

                  return (
                    <TableHead
                      key={header.id}
                      aria-sort={canSort ? ariaSortValue(sorted) : undefined}
                      className={cn(
                        "h-9 border-b border-border/40 text-xs font-medium text-muted-foreground",
                        sticky.className ?? "bg-muted/20",
                        isFirstColumn && "pl-4",
                        isLastColumn && "pr-4",
                        ALIGN_CLASS[align],
                        RESPONSIVE_CLASS[columnMeta.responsive ?? "always"],
                        columnMeta.className,
                      )}
                      style={sticky.style}
                    >
                      {header.isPlaceholder ? null : (
                        <span className={cn("inline-flex w-full items-center gap-1", ALIGN_FLEX_CLASS[align])}>
                          {canSort ? (
                            <button
                              type="button"
                              onClick={header.column.getToggleSortingHandler()}
                              className={cn(
                                "inline-flex items-center gap-1 rounded transition-colors hover:text-foreground",
                                sorted ? "text-foreground" : "text-muted-foreground",
                              )}
                            >
                              {flexRender(header.column.columnDef.header, header.getContext())}
                              {sorted === "asc" ? (
                                <ArrowUp aria-hidden className="size-3 shrink-0" />
                              ) : sorted === "desc" ? (
                                <ArrowDown aria-hidden className="size-3 shrink-0" />
                              ) : (
                                <ArrowUpDown aria-hidden className="size-3 shrink-0 opacity-30" />
                              )}
                            </button>
                          ) : (
                            flexRender(header.column.columnDef.header, header.getContext())
                          )}
                        </span>
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {pageRows.length > 0 ? (
              rowGroups.map((group) => (
                <Fragment key={group.key}>
                  {group.label !== null ? (
                    <TableRow className="hover:bg-transparent">
                      <TableCell
                        colSpan={bodyColumnCount}
                        className={cn(EYEBROW_CLASS, "border-b border-border/40 bg-muted/30 py-2 pl-4")}
                      >
                        {group.label}
                      </TableCell>
                    </TableRow>
                  ) : null}
                  {group.rows.map((row) => (
                    <Fragment key={row.id}>
                      <TableRow
                        data-row-id={row.id}
                        data-state={row.getIsSelected() && "selected"}
                        aria-current={row.id === inspectorId ? "true" : undefined}
                        className={cn(
                          "group border-b border-border/30 transition-colors hover:bg-accent/20 data-[state=selected]:bg-accent/30",
                          hasRowAction && "cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 focus-visible:ring-inset",
                          row.id === inspectorId && "bg-primary/10",
                        )}
                        onClick={(event) => handleRowClick(event, row)}
                        onDoubleClick={(event) => handleRowDoubleClick(event, row)}
                        onKeyDown={(event) => handleRowKeyDown(event, row)}
                        tabIndex={onRowClick ? 0 : undefined}
                        aria-describedby={onRowClick ? rowHintId : undefined}
                      >
                        {hasLeadingColumn ? renderLeadingCell(row) : null}
                        {row.getVisibleCells().map((cell, index) => {
                          const isActionColumn = cell.column.id === ADMIN_ACTION_COLUMN_ID;
                          const isFirstColumn = index === 0 && !hasLeadingColumn;
                          const isLastColumn = index === row.getVisibleCells().length - 1;
                          const columnMeta = readAdminColumnMeta<TData>(cell.column.columnDef.meta);
                          const align = columnMeta.align ?? (isActionColumn ? "right" : "left");
                          const sticky = stickyCell(cell.column.id, getColumnStyle(cell.column));

                          return (
                            <TableCell
                              key={cell.id}
                              className={cn(
                                "py-2.5 text-sm",
                                cellAlign === "top" ? "align-top" : "align-middle",
                                isFirstColumn && "pl-4 text-muted-foreground",
                                isLastColumn && "pr-4",
                                isActionColumn && "whitespace-nowrap",
                                columnMeta.numeric && "tabular-nums",
                                ALIGN_CLASS[align],
                                RESPONSIVE_CLASS[columnMeta.responsive ?? "always"],
                                columnMeta.className,
                                sticky.className,
                              )}
                              style={sticky.style}
                            >
                              {isActionColumn ? (
                                // Always visible: hiding the primary row
                                // actions behind hover made them unreachable
                                // without a mouse on every list screen.
                                <div className="flex w-full items-center justify-end">
                                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                </div>
                              ) : align === "left" ? (
                                flexRender(cell.column.columnDef.cell, cell.getContext())
                              ) : (
                                // `text-center` on the <td> does not centre a
                                // Tooltip/icon (inline-flex trigger inside a
                                // full-width cell). Match the header flex.
                                <div className={cn("flex w-full items-center", ALIGN_FLEX_CLASS[align])}>
                                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                                </div>
                              )}
                            </TableCell>
                          );
                        })}
                      </TableRow>
                      {renderExpanded && row.getIsExpanded() ? (
                        <TableRow className="hover:bg-transparent">
                          <TableCell colSpan={bodyColumnCount} className="border-b border-border/30 bg-muted/10 px-4 py-4">
                            {renderExpanded(row)}
                          </TableCell>
                        </TableRow>
                      ) : null}
                    </Fragment>
                  ))}
                </Fragment>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={bodyColumnCount} className="py-8 text-center">
                  {emptyState}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
        )}
      </div>

      {/* ── FOOTER: pagination ─────────────────────────── */}
      {safeTotal > 0 && isInfinite ? (
        <div className="border-t border-border/40 px-4 py-3">
          <InfiniteScrollFooter
            loaded={pageRows.length}
            total={safeTotal}
            unit={rowUnit}
            hasNextPage={pageRows.length < safeTotal}
            // Client mode already holds every row, so a batch appears in the
            // same commit — there is no in-flight page to report.
            isFetchingNextPage={false}
            fetchNextPage={() => setCurrentPage(safeCurrentPage + 1)}
          />
        </div>
      ) : null}
      {safeTotal > 0 && !isInfinite && (
        <div className="flex items-center justify-between gap-3 border-t border-border/40 px-4 py-2">
          <div className="flex items-center gap-3 text-sm text-muted-foreground">
            <span className="tabular-nums">{rangeStart}–{rangeEnd} of {safeTotal}</span>
            <div className="flex items-center gap-1.5">
              <span>Rows</span>
              <Select value={String(effectivePageSize)} onValueChange={(v) => handlePageSizeChange(Number(v))}>
                <SelectTrigger aria-label="Rows per page" className="h-8 w-auto gap-1 border-border bg-muted/30 px-2.5 text-sm tabular-nums text-muted-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {availablePageSizeOptions.map((opt) => (
                    <SelectItem key={opt} value={String(opt)} className="text-xs tabular-nums">{opt}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex items-center gap-1">
            <button
              onClick={() => setCurrentPage(Math.max(safeCurrentPage - 1, 1))}
              disabled={safeCurrentPage <= 1}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/30 hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
              aria-label="Previous page"
            >
              <ChevronLeft aria-hidden className="size-4" />
            </button>

            {(() => {
              const maxVisible = 5;

              const pageButton = (page: number) => (
                <button
                  key={page}
                  type="button"
                  onClick={() => setCurrentPage(page)}
                  aria-label={`Page ${page}`}
                  aria-current={safeCurrentPage === page ? "page" : undefined}
                  className={cn(
                    "flex size-7 items-center justify-center rounded-md text-xs tabular-nums transition-colors",
                    safeCurrentPage === page
                      ? "bg-primary text-primary-foreground font-medium"
                      : "text-muted-foreground hover:bg-accent/30 hover:text-foreground",
                  )}
                >
                  {page}
                </button>
              );

              const gap = (key: string) => (
                <span key={key} aria-hidden className="flex size-7 items-center justify-center text-xs text-muted-foreground">…</span>
              );

              if (totalPageCount <= maxVisible) {
                return Array.from({ length: totalPageCount }, (_, index) => pageButton(index + 1));
              }

              const pages: React.ReactNode[] = [pageButton(1)];
              if (safeCurrentPage > 3) pages.push(gap("gap-start"));
              const start = Math.max(2, safeCurrentPage - 1);
              const end = Math.min(totalPageCount - 1, safeCurrentPage + 1);
              for (let i = start; i <= end; i++) pages.push(pageButton(i));
              if (safeCurrentPage < totalPageCount - 2) pages.push(gap("gap-end"));
              pages.push(pageButton(totalPageCount));

              return pages;
            })()}

            <button
              onClick={() => setCurrentPage(Math.min(safeCurrentPage + 1, totalPageCount))}
              disabled={safeCurrentPage >= totalPageCount}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/30 hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
              aria-label="Next page"
            >
              <ChevronRight aria-hidden className="size-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
