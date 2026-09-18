"use client";

import React, { useCallback, useEffect, useId, useRef, useState } from "react";
import {
  Cell,
  Column,
  ColumnDef,
  ColumnFiltersState,
  ColumnOrderState,
  ColumnSizingState,
  flexRender,
  getCoreRowModel,
  getExpandedRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  Header,
  Row,
  RowSelectionState,
  SortingState,
  useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer, type VirtualItem } from "@tanstack/react-virtual";
import { closestCenter, DndContext, PointerSensor, useSensor, useSensors, type DragEndEvent } from "@dnd-kit/core";
import { arrayMove, horizontalListSortingStrategy, SortableContext, useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight, CircleMinus, Copy, Download, LoaderCircle, Rows3, Rows4, Search } from "lucide-react";
import { useDebounce } from "use-debounce";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn, EYEBROW_CLASS, Link, useIsMobile, useLocalStorageState, usePathname } from "./host";
import { ariaSortValue, type PaginatedResponse, type SortDir } from "./types";
import {
  collectFilterSpecs,
  parseFiltersFromParams,
  readAdminColumnFilter,
  serializeFilters,
  writeFiltersToParams,
  type AdminTableFilters
} from "./filters";
import {
  ALIGN_CLASS,
  ALIGN_FLEX_CLASS,
  RESPONSIVE_CLASS,
  readAdminColumnMeta,
  type AdminColumnCategory
} from "./columns";
import { CategorizedColumnPicker } from "@/components/ui/categorized-column-picker";
import { Checkbox } from "@/components/ui/checkbox";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuSeparator, ContextMenuTrigger } from "@/components/ui/context-menu";
import { InfiniteScrollFooter } from "@/components/ui/infinite-scroll";
import { useColumnVisibility } from "./useColumnVisibility";
import { isInteractiveRowTarget, useRowSelectionGestures } from "./useRowSelectionGestures";
import { AdminSavedViews } from "./SavedViews";
import { AdminTableSearchContext, HighlightMatch } from "./HighlightMatch";
import { downloadCsv } from "./csv";

const ADMIN_ACTION_COLUMN_ID = "actions";
const ADMIN_ACTION_COLUMN_MIN_WIDTH = 80;
/** Width of the select/expand column — keep in sync with its `w-10` class. */
const ADMIN_LEADING_COLUMN_WIDTH = 40;
/** Flexible (unsized, undragged) columns split this share of the table evenly, so they read as a grid instead of shrink-wrapping to content; the filler absorbs the rest. */
const ADMIN_FLEXIBLE_FILL_PERCENT = 75;
const DEFAULT_PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100];
/**
 * Rows past which the body is virtualised. Below it every row is in the DOM,
 * which keeps find-in-page and the tests' plain DOM queries working; above it
 * an infinite list of a few hundred `<tr>`s starts stuttering on scroll.
 */
const VIRTUALIZE_FROM = 100;
const ROW_HEIGHT_ESTIMATE = { comfortable: 41, compact: 33 } as const;
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

/** `?sort=a,b&dir=desc,asc` — one entry per sorted column, `dir` omitted when every one is ascending. */
function parseSorting(params: URLSearchParams, fallback: SortingState): SortingState {
  const sort = params.get("sort");
  if (!sort) return fallback;
  const dirs = (params.get("dir") ?? "").split(",");
  return sort.split(",").filter(Boolean).map((id, index) => ({ id, desc: parseSortDir(dirs[index] ?? null) === "desc" }));
}

function writeSorting(params: URLSearchParams, sorting: SortingState) {
  if (sorting.length === 0) { params.delete("sort"); params.delete("dir"); return; }
  params.set("sort", sorting.map((entry) => entry.id).join(","));
  if (sorting.some((entry) => entry.desc)) params.set("dir", sorting.map((entry) => (entry.desc ? "desc" : "asc")).join(","));
  else params.delete("dir");
}

function serializeSorting(sorting: SortingState) {
  return sorting.map((entry) => `${entry.id}:${entry.desc ? "desc" : "asc"}`).join(",");
}

/**
 * The id TanStack will give a column definition, before a table exists to ask.
 * Accessor columns fall back to their key; anything else must declare an `id`.
 */
function columnDefId<TData>(column: ColumnDef<TData>): string {
  if (column.id) return column.id;
  return "accessorKey" in column && typeof column.accessorKey === "string" ? column.accessorKey : "";
}

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
  // Every row at once: the caller already holds the whole pool and wants no
  // batching UI over it.
  const showAll = isClientMode && paging === "all";
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
  // Server mode sorts by one column: the backend takes a single `sort_by`.
  const sortField = sorting[0]?.id ?? null;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";
  const sortKey = serializeSorting(sorting);
  const previousDebouncedSearchRef = useRef("");
  const previousPageSizeRef = useRef(initialPageSize);
  const previousFilterKeyRef = useRef(filterKey);
  const previousSortRef = useRef("");
  const rowClickTimeoutRef = useRef<number | null>(null);
  const previousFiltersRef = useRef("");
  const previousUrlStateRef = useRef({ page: 1, search: "", pageSize: initialPageSize, sortKey: "", filters: "" });
  // Per-user table preferences. Widths and order are per screen (falling back
  // to the route when the screen gave no key); density is one setting everywhere.
  // ponytail: two tables on one route without `columnsStorageKey` share prefs.
  const prefsKey = columnsStorageKey ?? `admin-table:${pathname}`;
  const [density, setDensity] = useLocalStorageState<"comfortable" | "compact">("admin-table-density", "comfortable");
  const [columnSizing, setColumnSizing] = useLocalStorageState<ColumnSizingState>(`${prefsKey}:sizing`, {});
  const [savedColumnOrder, setColumnOrder] = useLocalStorageState<ColumnOrderState>(`${prefsKey}:order`, []);
  // The saved order is a preference over the columns that existed when it was
  // written. Columns added since (a conditional column, a custom field that
  // arrived from a query) would otherwise be appended after the actions
  // column, so the order handed to TanStack is rebuilt every render: known
  // columns in saved order, new ones in definition order, actions last.
  const definedColumnIds = columns.map(columnDefId).filter((id) => id && id !== ADMIN_ACTION_COLUMN_ID);
  const columnOrder: ColumnOrderState = [
    ...savedColumnOrder.filter((id) => definedColumnIds.includes(id)),
    ...definedColumnIds.filter((id) => !savedColumnOrder.includes(id)),
    ...(columns.some((column) => columnDefId(column) === ADMIN_ACTION_COLUMN_ID) ? [ADMIN_ACTION_COLUMN_ID] : [])
  ];
  const [focusedRowId, setFocusedRowId] = useState<string | null>(null);
  /** Text of the cell under the last right-click, offered as "Copy" in the row menu. */
  const [contextCell, setContextCell] = useState("");
  const [scrollElement, setScrollElement] = useState<HTMLElement | null>(null);
  // The shadcn `Table` wraps the `<table>` in the element that actually scrolls.
  const tableRef = useCallback((table: HTMLTableElement | null) => setScrollElement(table?.parentElement ?? null), []);
  const cardRef = useRef<HTMLDivElement>(null);

  // The scroll box takes whatever height is left below it in the viewport, so
  // the page itself never needs to scroll and the table is the one scrollable
  // thing on screen. Measured rather than laid out with flex: the box sits
  // under a dozen different screens' headers and tabs, none of which would
  // otherwise have to know about it.
  useEffect(() => {
    const card = cardRef.current;
    if (!scrollElement || !card) return;
    let frame = 0;
    const fit = () => {
      frame = 0;
      // Measure with the cap lifted: with the box capped, a page shorter than
      // the viewport reports the slack under the card as "content below", and
      // the cap would lock at whatever height the box happened to have.
      scrollElement.style.maxHeight = "";
      const cardRect = card.getBoundingClientRect();
      const chrome = cardRect.height - scrollElement.getBoundingClientRect().height;
      const cardTop = cardRect.top + window.scrollY;
      const below = Math.max(0, document.documentElement.scrollHeight - (cardRect.bottom + window.scrollY));
      scrollElement.style.maxHeight = `${Math.max(240, window.innerHeight - cardTop - chrome - below)}px`;
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(fit); };
    fit();
    window.addEventListener("resize", schedule);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    // The table grows and shrinks with its rows inside a capped box, which the
    // box itself never reports; the card reports toolbar/footer changes.
    // ponytail: headers collapsing above the card on a page that does not
    // overflow are not observed; add an observer on the page container if it shows.
    observer?.observe(scrollElement.firstElementChild ?? scrollElement);
    observer?.observe(card);
    return () => {
      window.removeEventListener("resize", schedule);
      observer?.disconnect();
      if (frame) cancelAnimationFrame(frame);
    };
  }, [scrollElement]);
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
    if (previousSortRef.current !== sortKey) {
      previousSortRef.current = sortKey;
      setCurrentPage(1);
    }
  }, [sortKey]);

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
  const { visibility, toggleColumn, setVisibility, resetToDefaults } = useColumnVisibility(
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
  // `all` is one page big enough to hold every row `clientRows` can yield.
  const paginationState = showAll
    ? { pageIndex: 0, pageSize: Math.max(clientRows.length, 1) }
    : isInfinite
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
    // Shift+click stacks sorts in client mode; server mode takes one column.
    enableMultiSort: isClientMode,
    isMultiSortEvent: (event) => (event as React.MouseEvent).shiftKey,
    enableColumnResizing: true,
    // One write per drag rather than one per pointer move: sizing is persisted.
    columnResizeMode: "onEnd",
    onColumnSizingChange: setColumnSizing,
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
      columnSizing,
      columnOrder,
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
  const pageRows = table.getRowModel().rows;
  // Server mode only holds the current page, so a row selected two pages back
  // would vanish from `bulkActions` while its checkbox state lived on. Remember
  // every selected row's data as it passes through; forget it when deselected.
  const selectedDataRef = useRef(new Map<string, TData>());
  for (const row of pageRows) if (row.getIsSelected()) selectedDataRef.current.set(row.id, row.original);
  for (const id of selectedDataRef.current.keys()) if (!rowSelection[id]) selectedDataRef.current.delete(id);
  const selectedData = [...selectedDataRef.current.values()];
  const selectedOnPage = pageRows.filter((row) => row.getIsSelected()).length;
  const gestures = useRowSelectionGestures(table, Boolean(enableRowSelection));
  const selectableRows = enableRowSelection ? pageRows.filter((row) => row.getCanSelect()) : [];

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
      const nextSorting = parseSorting(params, initialSort ? [{ id: initialSort.field, desc: initialSort.dir === "desc" }] : []);
      const nextSortKey = serializeSorting(nextSorting);
      const nextFilters = parseFiltersFromParams(filterSpecsRef.current, params);
      const nextSerializedFilters = serializeFilters(nextFilters);

      previousDebouncedSearchRef.current = nextSearch;
      previousPageSizeRef.current = nextPageSize;
      previousSortRef.current = nextSortKey;
      previousFiltersRef.current = nextSerializedFilters;
      previousUrlStateRef.current = { page: nextPage, search: nextSearch, pageSize: nextPageSize, sortKey: nextSortKey, filters: nextSerializedFilters };
      pendingUrlFiltersRef.current = nextSerializedFilters;
      setCurrentPage(nextPage);
      setSearchValue(nextSearch);
      setPageSize(nextPageSize);
      setSorting(nextSorting);
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
    const sortChanged = prev.sortKey !== sortKey;
    const filtersChanged = prev.filters !== serializedFilters;

    if (!searchChanged && !pageChanged && !pageSizeChanged && !sortChanged && !filtersChanged) return;

    const currentSearch = params.get("search") ?? "";
    const currentPageParam = Number.parseInt(params.get("page") ?? "1", 10) || 1;
    const currentPageSizeParam = parsePositiveInt(params.get("per_page"), initialPageSize);
    const currentSortKey = serializeSorting(parseSorting(params, []));
    const currentFilters = serializeFilters(parseFiltersFromParams(filterSpecsRef.current, params));

    if (
      currentSearch === debouncedSearchValue &&
      currentPageParam === safeCurrentPage &&
      currentPageSizeParam === safePageSize &&
      currentSortKey === sortKey &&
      currentFilters === serializedFilters
    ) {
      previousUrlStateRef.current = { page: safeCurrentPage, search: debouncedSearchValue, pageSize: safePageSize, sortKey, filters: serializedFilters };
      return;
    }

    if (debouncedSearchValue) params.set("search", debouncedSearchValue); else params.delete("search");
    if (safeCurrentPage > 1) params.set("page", String(safeCurrentPage)); else params.delete("page");
    if (safePageSize !== initialPageSize) params.set("per_page", String(safePageSize)); else params.delete("per_page");
    writeSorting(params, sorting);
    writeFiltersToParams(filterSpecsRef.current, filters, params);

    const query = params.toString();
    const nextUrl = query ? `${pathname}?${query}` : pathname;

    if (searchChanged || pageSizeChanged || sortChanged || filtersChanged) {
      window.history.replaceState(null, "", nextUrl);
    } else {
      window.history.pushState(null, "", nextUrl);
    }

    previousUrlStateRef.current = { page: safeCurrentPage, search: debouncedSearchValue, pageSize: safePageSize, sortKey, filters: serializedFilters };
  }, [safeCurrentPage, debouncedSearchValue, initialPageSize, safePageSize, pathname, sorting, sortKey, filters, serializedFilters]);

  // react-table merges an internal `defaultColumn.size` (150) into every
  // column's runtime `columnDef.size`, so that field can't tell "the caller
  // set a size" from "no one did" — check the raw prop instead.
  const explicitlySizedColumnIds = new Set(columns.filter((c) => typeof c.size === "number").map(columnDefId));

  /** Excludes the actions column, dragged/explicitly sized columns, and sticky columns (which must declare a size; see the offset loop below). */
  const isFlexibleColumn = (column: Column<TData, unknown>) =>
    column.id !== ADMIN_ACTION_COLUMN_ID &&
    columnSizing[column.id] === undefined &&
    !explicitlySizedColumnIds.has(column.id) &&
    !readAdminColumnMeta<TData>(column.columnDef.meta).sticky;

  const getColumnStyle = (column: Column<TData, unknown>) => {
    if (column.id === ADMIN_ACTION_COLUMN_ID) {
      // Exactly as wide as its menu button, whatever a saved sizing says: the
      // column is not resizable now, but an earlier build let it be dragged.
      const width = Math.max(column.columnDef.size ?? 0, ADMIN_ACTION_COLUMN_MIN_WIDTH);
      return { width, minWidth: width, maxWidth: width };
    }
    const resized = columnSizing[column.id] !== undefined;
    if (resized || explicitlySizedColumnIds.has(column.id)) {
      const configuredSize = column.getSize();
      // Auto table layout treats `width` as a floor; a user-dragged width is a
      // ceiling too, or shrinking a column would visibly do nothing.
      return resized
        ? { width: configuredSize, minWidth: configuredSize, maxWidth: configuredSize }
        : { width: configuredSize, minWidth: configuredSize };
    }
    if (!isFlexibleColumn(column)) return undefined;
    // No explicit or dragged width: split an even share of the table so the
    // grid fills the screen instead of shrink-wrapping to content with a
    // dead gap on the right (the filler, below, absorbs what's left).
    const flexibleCount = table.getVisibleLeafColumns().filter(isFlexibleColumn).length;
    return flexibleCount > 0 ? { width: `${ADMIN_FLEXIBLE_FILL_PERCENT / flexibleCount}%` } : undefined;
  };

  const hasRowAction = Boolean(onRowClick || onRowDoubleClick);

  const handleRowClick = (event: React.MouseEvent<HTMLTableRowElement>, row: Row<TData>) => {
    // A sweep, Ctrl+click or Shift+click ends in a click too; that one selected, it does not open.
    if (gestures.consumeClick()) return;
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

  /** Arrow/Space/Escape/Ctrl+A go to the selection gestures; Enter (and Space without selection) opens the row. */
  const handleBodyKeyDown = (event: React.KeyboardEvent<HTMLTableSectionElement>) => {
    if (gestures.bodyKeyDown(event)) return;
    if (!onRowClick) return;
    const target = event.target as HTMLElement;
    if (target.dataset.rowId === undefined) return;
    const row = table.getRowModel().rowsById[target.dataset.rowId];
    if (row && (event.key === "Enter" || (event.key === " " && !enableRowSelection))) {
      event.preventDefault();
      onRowClick(row);
    }
  };

  const hasLeadingColumn = Boolean(enableRowSelection || renderExpanded);
  const leadingColumnCount = hasLeadingColumn ? 1 : 0;
  const visibleColumns = table.getVisibleLeafColumns();
  // +1 for the filler column that swallows leftover width, keeping data columns
  // packed at their content width instead of stretched proportionally.
  const bodyColumnCount = visibleColumns.length + leadingColumnCount + 1;
  const hasActionColumn = visibleColumns.some((column) => column.id === ADMIN_ACTION_COLUMN_ID);
  /** Filler goes in front of the actions column, or at the very end without one. */
  const fillerIndex = hasActionColumn ? visibleColumns.length - 1 : visibleColumns.length;

  // Sticky pins a left-edge PREFIX of the visible columns: a pinned column with
  // scrolling ones in front of it would park itself over the wrong neighbours.
  // Offsets are summed from declared (or dragged) sizes rather than measured,
  // so every pinned column after the first must set `size`.
  const stickyLeft = new Map<string, number>();
  let stickyOffset = hasLeadingColumn ? ADMIN_LEADING_COLUMN_WIDTH : 0;
  for (const column of visibleColumns) {
    if (!readAdminColumnMeta<TData>(column.columnDef.meta).sticky) break;
    stickyLeft.set(column.id, stickyOffset);
    const width = getColumnStyle(column)?.width;
    stickyOffset += typeof width === "number" ? width : 0;
  }
  const lastStickyId = [...stickyLeft.keys()].pop() ?? null;
  // The pinned block ends in a hard edge that scrolling content slides under;
  // the default 8px on either side of it reads as none, so both neighbours of
  // the edge get the same inset the table's outer edges have.
  const firstScrollingId = lastStickyId ? (visibleColumns[stickyLeft.size]?.id ?? null) : null;
  const edgePadding = (columnId: string) =>
    cn(columnId === lastStickyId && "pr-4", columnId === firstScrollingId && "pl-4");

  /** Sticky class + `left` for a data cell, or nothing when it is not pinned. */
  const stickyCell = (columnId: string, style?: React.CSSProperties) => {
    const left = stickyLeft.get(columnId);
    if (left === undefined) return { className: undefined, style };
    return {
      className: cn("admin-sticky-col", columnId === lastStickyId && "admin-sticky-col-edge"),
      style: { ...style, left }
    };
  };
  const rowGroups = groupRows
    ? groupRows(pageRows)
    : [{ key: "all", label: null, rows: pageRows }];

  // One flat list of everything the body renders, so the virtualiser can
  // measure group headers and expanded details like any other row.
  type BodyItem =
    | { kind: "group"; key: string; group: AdminDataTableGroup<TData> }
    | { kind: "row"; key: string; row: Row<TData> }
    | { kind: "detail"; key: string; row: Row<TData> };
  const bodyItems: BodyItem[] = rowGroups.flatMap((group) => [
    ...(group.label !== null ? [{ kind: "group" as const, key: `group:${group.key}`, group }] : []),
    ...group.rows.flatMap((row) => [
      { kind: "row" as const, key: row.id, row },
      ...(renderExpanded && row.getIsExpanded() ? [{ kind: "detail" as const, key: `detail:${row.id}`, row }] : [])
    ])
  ]);
  const virtualize = !isMobile && bodyItems.length > VIRTUALIZE_FROM;
  const virtualizer = useVirtualizer({
    count: bodyItems.length,
    getScrollElement: () => scrollElement,
    estimateSize: () => ROW_HEIGHT_ESTIMATE[density],
    getItemKey: (index) => bodyItems[index].key,
    overscan: 12,
    enabled: virtualize
  });
  const virtualItems = virtualize ? virtualizer.getVirtualItems() : [];
  const firstRowId = bodyItems.find((item) => item.kind === "row")?.row.id ?? null;
  // Roving tabindex: one row is in the Tab order, arrows move between the rest.
  const tabbableRowId = focusedRowId !== null && table.getRowModel().rowsById[focusedRowId] ? focusedRowId : firstRowId;

  // Column drag-to-reorder. Only the header row is sortable; the actions
  // column keeps its place at the right edge.
  const dndSensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const handleColumnDragEnd = ({ active, over }: DragEndEvent) => {
    if (!over || active.id === over.id) return;
    setColumnOrder(arrayMove(columnOrder, columnOrder.indexOf(String(active.id)), columnOrder.indexOf(String(over.id))));
  };

  /** Selected rows when there are any, else the whole current view (every filtered row in client mode). */
  const exportCsv = () => {
    const exportColumns = visibleColumns.filter((column) => column.id !== ADMIN_ACTION_COLUMN_ID);
    const source = isClientMode ? table.getFilteredRowModel().rows : pageRows;
    const rows = selectedData.length > 0 ? source.filter((row) => row.getIsSelected()) : source;
    downloadCsv(pathname.split("/").filter(Boolean).pop() ?? "export", [
      exportColumns.map((column) => (typeof column.columnDef.header === "string" ? column.columnDef.header : column.id)),
      ...rows.map((row) => exportColumns.map((column) => row.getValue(column.id)))
    ]);
  };

  // Right-click / long-press menu mirrors the kebab column, when a screen has one.
  const rowActions = columns.map((column) => readAdminColumnMeta<TData>(column.meta).rowActions).find(Boolean);
  // Only cells left on TanStack's default renderer get search highlighting;
  // custom cells opt in through `useAdminTableSearch`.
  const customCellIds = new Set(columns.filter((column) => column.cell !== undefined).map(columnDefId));

  const cellPadding = density === "compact" ? "py-1" : "py-2.5";

  const renderLeadingCell = (row: Row<TData>) => (
    <TableCell
      className={cn(
        "w-10 pl-4",
        cellPadding,
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
            onPointerDown={gestures.checkboxPointerDown(row)}
            onClick={gestures.checkboxClick}
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
  };

  // Auto table layout hands leftover width to every column in proportion to
  // its content, which reads as random gaps between columns. Flexible columns
  // (see `getColumnStyle`) now claim an even `ADMIN_FLEXIBLE_FILL_PERCENT`
  // share instead, so the grid fills the screen; the filler only mops up
  // whatever's left over (all of it, if every column turned out sized/sticky).
  const flexibleColumnCount = visibleColumns.filter(isFlexibleColumn).length;
  const fillerStyle = flexibleColumnCount > 0 ? { width: `${100 - ADMIN_FLEXIBLE_FILL_PERCENT}%` } : undefined;
  const fillerHead = (
    <TableHead
      key="filler"
      aria-hidden
      className={cn("border-b border-border/40 p-0 admin-table-head", !fillerStyle && "w-full", density === "compact" ? "h-8" : "h-9")}
      style={fillerStyle}
    />
  );
  const fillerCell = <TableCell key="filler" aria-hidden className={cn("p-0", !fillerStyle && "w-full")} style={fillerStyle} />;

  const renderHead = (header: Header<TData, unknown>, index: number, count: number) => {
    const isActionColumn = header.column.id === ADMIN_ACTION_COLUMN_ID;
    const isFirstColumn = index === 0 && !hasLeadingColumn;
    const isLastColumn = index === count - 1;
    const canSort = header.column.getCanSort();
    const sorted = header.column.getIsSorted();
    const sortIndex = sorting.length > 1 ? header.column.getSortIndex() : -1;
    const columnMeta = readAdminColumnMeta<TData>(header.column.columnDef.meta);
    const align = columnMeta.align ?? (isActionColumn ? "right" : "left");
    const sticky = stickyCell(header.column.id, getColumnStyle(header.column));

    return (
      <SortableHead
        key={header.id}
        header={header}
        disabled={isActionColumn}
        aria-sort={canSort ? ariaSortValue(sorted) : undefined}
        className={cn(
          "border-b border-border/40 text-xs font-medium text-muted-foreground",
          density === "compact" ? "h-8" : "h-9",
          sticky.className ?? "admin-table-head",
          isFirstColumn && "pl-4",
          isLastColumn && "pr-4",
          edgePadding(header.column.id),
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
                title={isClientMode ? "Click to sort, Shift+click to add a second sort" : undefined}
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
                {sortIndex >= 0 ? (
                  <span aria-label={`Sort priority ${sortIndex + 1}`} className="font-mono text-[10px] tabular-nums opacity-70">{sortIndex + 1}</span>
                ) : null}
              </button>
            ) : (
              flexRender(header.column.columnDef.header, header.getContext())
            )}
          </span>
        )}
      </SortableHead>
    );
  };

  const renderCell = (cell: Cell<TData, unknown>, index: number, count: number) => {
    const isActionColumn = cell.column.id === ADMIN_ACTION_COLUMN_ID;
    const isFirstColumn = index === 0 && !hasLeadingColumn;
    const isLastColumn = index === count - 1;
    const columnMeta = readAdminColumnMeta<TData>(cell.column.columnDef.meta);
    const align = columnMeta.align ?? (isActionColumn ? "right" : "left");
    const sticky = stickyCell(cell.column.id, getColumnStyle(cell.column));
    const content =
      debouncedSearchValue && !isActionColumn && !customCellIds.has(cell.column.id) ? (
        <HighlightMatch text={String(cell.getValue() ?? "")} query={debouncedSearchValue} />
      ) : (
        flexRender(cell.column.columnDef.cell, cell.getContext())
      );

    return (
      <TableCell
        key={cell.id}
        className={cn(
          "text-sm",
          cellPadding,
          cellAlign === "top" ? "align-top" : "align-middle",
          isFirstColumn && "pl-4 text-muted-foreground",
          isLastColumn && "pr-4",
          edgePadding(cell.column.id),
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
          // The kebab gates its own visibility (hover, focus-within, touch);
          // this wrapper only aligns it.
          <div className="flex w-full items-center justify-end">{content}</div>
        ) : align === "left" ? (
          content
        ) : (
          // `text-center` on the <td> does not centre a Tooltip/icon
          // (inline-flex trigger inside a full-width cell). Match the header flex.
          <div className={cn("flex w-full items-center", ALIGN_FLEX_CLASS[align])}>{content}</div>
        )}
      </TableCell>
    );
  };

  const renderRow = (row: Row<TData>, virtual?: VirtualItem) => {
    const cells = row.getVisibleCells();
    const tr = (
      <TableRow
        ref={virtual ? virtualizer.measureElement : undefined}
        data-index={virtual?.index}
        data-row-id={row.id}
        data-selected={row.getIsSelected() || undefined}
        aria-current={row.id === inspectorId ? "true" : undefined}
        tabIndex={row.id === tabbableRowId ? 0 : -1}
        onFocus={(event) => { if (event.target === event.currentTarget) setFocusedRowId(row.id); }}
        className={cn(
          "group border-b border-border/30 transition-colors hover:bg-accent/20 data-[selected]:bg-accent/30",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 focus-visible:ring-inset",
          hasRowAction && "cursor-pointer",
          row.id === inspectorId && "bg-primary/10",
        )}
        onPointerDown={gestures.rowPointerDown(row)}
        onClick={(event) => handleRowClick(event, row)}
        onDoubleClick={(event) => handleRowDoubleClick(event, row)}
        onContextMenu={(event) => {
          const td = (event.target as HTMLElement).closest("td");
          setContextCell(td ? td.textContent.trim() : "");
        }}
        aria-describedby={rowHintId}
      >
        {hasLeadingColumn ? renderLeadingCell(row) : null}
        {cells.flatMap((cell, index) => [
          ...(index === fillerIndex ? [fillerCell] : []),
          renderCell(cell, index, cells.length)
        ])}
        {fillerIndex === cells.length ? fillerCell : null}
      </TableRow>
    );
    const actions = rowActions?.(row.original).filter((action) => !action.hidden) ?? [];
    return (
      <ContextMenu key={row.id}>
        <ContextMenuTrigger asChild>{tr}</ContextMenuTrigger>
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
  };

  const renderItem = (item: BodyItem, virtual?: VirtualItem) => {
    const measure = virtual ? { ref: virtualizer.measureElement, "data-index": virtual.index } : {};
    if (item.kind === "row") return renderRow(item.row, virtual);
    if (item.kind === "group") {
      return (
        <TableRow key={item.key} {...measure} className="hover:bg-transparent">
          <TableCell colSpan={bodyColumnCount} className={cn(EYEBROW_CLASS, "border-b border-border/40 bg-muted/30 py-2 pl-4")}>
            {item.group.label}
          </TableCell>
        </TableRow>
      );
    }
    return (
      <TableRow key={item.key} {...measure} className="hover:bg-transparent">
        <TableCell colSpan={bodyColumnCount} className="border-b border-border/30 bg-muted/10 px-4 py-4">
          {renderExpanded?.(item.row)}
        </TableCell>
      </TableRow>
    );
  };

  const padTop = virtualItems[0]?.start ?? 0;
  const padBottom = virtualItems.length > 0 ? virtualizer.getTotalSize() - virtualItems[virtualItems.length - 1].end : 0;
  const offPageSelected = selectedData.length - selectedOnPage;

  return (
    <AdminTableSearchContext.Provider value={debouncedSearchValue}>
    <div ref={cardRef} className="rounded-xl border border-border/50 bg-card/50 overflow-hidden">
      {/* ── TOOLBAR ─────────────────────────────────────── */}
      {/* One row: search, then the screen's filter bar (chips wrap inside it),
          then the table's own controls. Two stacked rows cost a full band of
          chrome for a chip row that is empty most of the time. */}
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
          {bulkActions && selectedData.length > 0 ? bulkActions(selectedData, () => setRowSelection({})) : null}
          {offPageSelected > 0 ? (
            <span className="text-xs tabular-nums text-muted-foreground" title="Selected rows not on this page are included in bulk actions">
              {offPageSelected} on other pages
            </span>
          ) : null}
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8"
            onClick={exportCsv}
            disabled={pageRows.length === 0}
            title={selectedData.length > 0 ? `Export ${selectedData.length} selected rows as CSV` : "Export the current view as CSV"}
          >
            <Download aria-hidden className="size-3.5" />
            CSV
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="h-8 w-8 px-0"
            aria-pressed={density === "compact"}
            aria-label={density === "compact" ? "Comfortable rows" : "Compact rows"}
            title={density === "compact" ? "Comfortable rows" : "Compact rows"}
            onClick={() => setDensity(density === "compact" ? "comfortable" : "compact")}
          >
            {density === "compact" ? <Rows3 aria-hidden className="size-3.5" /> : <Rows4 aria-hidden className="size-3.5" />}
          </Button>
          <AdminSavedViews
            storageKey={prefsKey}
            extra={{ get: () => visibility, apply: (next) => setVisibility(next as Record<string, boolean>) }}
          />
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

      {/* ── TABLE ───────────────────────────────────────── */}
      <div>
        <p id={rowHintId} className="sr-only">
          Use the Up and Down arrows to move between rows
          {enableRowSelection ? ", Space to select, Shift with an arrow to extend the selection" : ""}
          {onRowClick ? ", Enter to open the focused row" : ""}.
        </p>
        {isMobile ? (
          pageRows.length > 0 ? (
            <ul aria-label="Rows">{rowGroups.flatMap((group) => group.rows).map(renderMobileRow)}</ul>
          ) : (
            <div className="py-8 text-center">{emptyState}</div>
          )
        ) : (
        <DndContext sensors={dndSensors} collisionDetection={closestCenter} onDragEnd={handleColumnDragEnd}>
        <SortableContext
          items={visibleColumns.filter((column) => column.id !== ADMIN_ACTION_COLUMN_ID).map((column) => column.id)}
          strategy={horizontalListSortingStrategy}
        >
        {/* The table scrolls in its own box so the header can stick and the
            body can be virtualised; the box's height is measured to fill the
            viewport (see the effect on `scrollElement`). */}
        <Table ref={tableRef} className="min-w-full border-separate border-spacing-0">
          <TableHeader className="sticky top-0 z-10">
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent">
                {hasLeadingColumn ? (
                  <TableHead
                    className={cn(
                      "w-10 border-b border-border/40 pl-4 text-left",
                      density === "compact" ? "h-8" : "h-9",
                      stickyLeft.size > 0 ? "admin-sticky-col" : "admin-table-head"
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
                {headerGroup.headers.flatMap((header, index) => [
                  ...(index === fillerIndex ? [fillerHead] : []),
                  renderHead(header, index, headerGroup.headers.length)
                ])}
                {fillerIndex === headerGroup.headers.length ? fillerHead : null}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody onKeyDown={handleBodyKeyDown}>
            {bodyItems.length === 0 ? (
              <TableRow>
                <TableCell colSpan={bodyColumnCount} className="py-8 text-center">
                  {emptyState}
                </TableCell>
              </TableRow>
            ) : virtualize ? (
              <>
                {padTop > 0 ? <tr aria-hidden style={{ height: padTop }} /> : null}
                {virtualItems.map((virtual) => renderItem(bodyItems[virtual.index], virtual))}
                {padBottom > 0 ? <tr aria-hidden style={{ height: padBottom }} /> : null}
              </>
            ) : (
              bodyItems.map((item) => renderItem(item))
            )}
            {safeTotal > 0 && isInfinite ? (
              // Inside the scroll box, where the sentinel is only in view once
              // the user has actually reached the bottom of the loaded rows.
              <TableRow className="hover:bg-transparent">
                <TableCell colSpan={bodyColumnCount} className="border-t border-border/40 px-4 py-3">
                  <InfiniteScrollFooter
                    root={scrollElement}
                    loaded={pageRows.length}
                    total={safeTotal}
                    unit={rowUnit}
                    hasNextPage={pageRows.length < safeTotal}
                    // Client mode already holds every row, so a batch appears in
                    // the same commit — there is no in-flight page to report.
                    isFetchingNextPage={false}
                    fetchNextPage={() => setCurrentPage(safeCurrentPage + 1)}
                  />
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
        </SortableContext>
        </DndContext>
        )}
      </div>

      {/* ── FOOTER: pagination ─────────────────────────── */}
      {safeTotal > 0 && !isInfinite && !showAll && (
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
    </AdminTableSearchContext.Provider>
  );
}

/**
 * Header cell that can be dragged to reorder its column and has a resize
 * handle on its right edge. Only dnd-kit's pointer listeners are spread, not
 * its `attributes`: those would put `role="button"` on a `<th>`.
 */
function SortableHead<TData>({
  header,
  disabled,
  className,
  style,
  children,
  ...rest
}: Readonly<
  { header: Header<TData, unknown>; disabled?: boolean } & React.ThHTMLAttributes<HTMLTableCellElement>
>) {
  const { setNodeRef, listeners, transform, transition, isDragging } = useSortable({ id: header.column.id, disabled });
  const resizeHandler = header.getResizeHandler();
  return (
    <TableHead
      ref={setNodeRef}
      {...rest}
      {...listeners}
      className={cn(className, "relative select-none", isDragging && "z-20 opacity-70")}
      style={{ ...style, transform: CSS.Translate.toString(transform), transition }}
    >
      {children}
      {header.column.getCanResize() ? (
        <div
          role="separator"
          aria-orientation="vertical"
          aria-label={`Resize ${header.column.id} column`}
          title="Drag to resize, double-click to reset"
          onPointerDown={(event) => event.stopPropagation()}
          onMouseDown={resizeHandler}
          onTouchStart={resizeHandler}
          onDoubleClick={() => header.column.resetSize()}
          className={cn(
            "absolute right-0 top-0 h-full w-1.5 cursor-col-resize touch-none hover:bg-primary/40",
            header.column.getIsResizing() && "bg-primary"
          )}
        />
      ) : null}
    </TableHead>
  );
}
