"use client";

import React, { useEffect, useRef, useState } from "react";
import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  SortingState,
  useReactTable,
  Row,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, CircleMinus, LoaderCircle, Search } from "lucide-react";
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
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { cn } from "@/lib/utils";

const ADMIN_ACTION_COLUMN_ID = "actions";
const ADMIN_ACTION_COLUMN_MIN_WIDTH = 80;
const DEFAULT_PAGE_SIZE_OPTIONS = [10, 15, 25, 50, 100];

function parsePositiveInt(value: string | null, fallback: number) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function parseSortDir(value: string | null): SortDir {
  return value === "desc" ? "desc" : "asc";
}

export type SortDir = "asc" | "desc";

export interface AdminDataTableProps<TData> {
  initialData?: PaginatedResponse<TData>;
  queryKey: (page: number, search: string, pageSize: number, sortField: string | null, sortDir: SortDir) => readonly unknown[];
  queryFn: (page: number, search: string, pageSize: number, sortField: string | null, sortDir: SortDir) => Promise<PaginatedResponse<TData>>;

  columns: ColumnDef<TData>[];
  searchPlaceholder?: string;
  emptyMessage?: string;
  initialPageSize?: number;
  pageSizeOptions?: number[];

  onRowClick?: (row: Row<TData>) => void;
  onRowDoubleClick?: (row: Row<TData>) => void;
  actions?: React.ReactNode;

  initialPage?: number;
  initialSearch?: string;
}

export function AdminDataTable<TData>({
  initialData,
  queryKey,
  queryFn,
  columns,
  searchPlaceholder = "Search...",
  emptyMessage = "No results found.",
  onRowClick,
  onRowDoubleClick,
  actions,
  initialPage = 1,
  initialSearch = "",
  initialPageSize = 15,
  pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
}: AdminDataTableProps<TData>) {
  const pathname = usePathname();
  const defaultPageSize = initialData?.per_page && initialData.per_page > 0 ? initialData.per_page : initialPageSize;
  const [searchValue, setSearchValue] = useState<string>(initialSearch);
  const [debouncedSearchValue] = useDebounce(searchValue, 300);
  const [currentPage, setCurrentPage] = useState<number>(initialPage);
  const [pageSize, setPageSize] = useState<number>(defaultPageSize);
  const [sorting, setSorting] = useState<SortingState>([]);
  const sortField = sorting[0]?.id ?? null;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";
  const previousDebouncedSearchRef = useRef(initialSearch);
  const previousPageSizeRef = useRef(defaultPageSize);
  const previousSortRef = useRef<{ field: string | null; dir: SortDir }>({ field: null, dir: "asc" });
  const previousUrlStateRef = useRef({ page: initialPage, search: initialSearch, pageSize: defaultPageSize, sortField: null as string | null, sortDir: "asc" as SortDir });
  const rowClickTimeoutRef = useRef<number | null>(null);
  const safeCurrentPage = Number.isFinite(currentPage) && currentPage > 0 ? currentPage : initialPage;
  const safePageSize = Number.isFinite(pageSize) && pageSize > 0 ? pageSize : defaultPageSize;

  useEffect(() => {
    previousDebouncedSearchRef.current = initialSearch;
    setSearchValue(initialSearch);
  }, [initialSearch]);

  useEffect(() => {
    setPageSize(defaultPageSize);
    previousPageSizeRef.current = defaultPageSize;
  }, [defaultPageSize]);

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
    const prev = previousSortRef.current;
    if (prev.field !== sortField || prev.dir !== sortDir) {
      previousSortRef.current = { field: sortField, dir: sortDir };
      setCurrentPage(1);
    }
  }, [sortField, sortDir]);

  const dataQuery = useQuery({
    queryKey: queryKey(safeCurrentPage, debouncedSearchValue, safePageSize, sortField, sortDir),
    queryFn: () => queryFn(safeCurrentPage, debouncedSearchValue, safePageSize, sortField, sortDir),
    placeholderData: (previousData) => previousData,
    initialData:
      initialData &&
      safeCurrentPage === initialPage &&
      debouncedSearchValue === initialSearch &&
      safePageSize === defaultPageSize &&
      sortField === null
        ? initialData
        : undefined,
  });

  const data = dataQuery.data ?? initialData ?? { results: [], total: 0, page: 1, per_page: safePageSize };
  const isRefreshing = dataQuery.isFetching && !dataQuery.isLoading;
  const safeTotal = Number.isFinite(data.total) ? data.total : 0;
  const responsePageSize = Number.isFinite(data.per_page) ? data.per_page : undefined;
  const effectivePageSize = responsePageSize && responsePageSize > 0 ? responsePageSize : safePageSize;
  const availablePageSizeOptions = Array.from(new Set([...pageSizeOptions, effectivePageSize])).sort((a, b) => a - b);
  const totalPageCount = Math.max(1, Math.ceil(safeTotal / effectivePageSize));
  const rangeStart = safeTotal > 0 ? (safeCurrentPage - 1) * effectivePageSize + 1 : 0;
  const rangeEnd = safeTotal > 0 ? Math.min(safeCurrentPage * effectivePageSize, safeTotal) : 0;

  useEffect(() => {
    if (safeCurrentPage > totalPageCount) {
      setCurrentPage(totalPageCount);
    }
  }, [safeCurrentPage, totalPageCount]);

  // Browser back/forward sync
  useEffect(() => {
    const syncStateFromUrl = () => {
      const params = new URLSearchParams(window.location.search);
      const nextPage = parsePositiveInt(params.get("page"), initialPage);
      const nextSearch = params.get("search") ?? initialSearch;
      const nextPageSize = parsePositiveInt(params.get("per_page"), defaultPageSize);
      const nextSortField = params.get("sort") ?? null;
      const nextSortDir = parseSortDir(params.get("dir"));

      previousDebouncedSearchRef.current = nextSearch;
      previousPageSizeRef.current = nextPageSize;
      previousSortRef.current = { field: nextSortField, dir: nextSortDir };
      previousUrlStateRef.current = { page: nextPage, search: nextSearch, pageSize: nextPageSize, sortField: nextSortField, sortDir: nextSortDir };
      setCurrentPage(nextPage);
      setSearchValue(nextSearch);
      setPageSize(nextPageSize);
      setSorting(nextSortField ? [{ id: nextSortField, desc: nextSortDir === "desc" }] : []);
    };

    syncStateFromUrl();
    window.addEventListener("popstate", syncStateFromUrl);
    return () => window.removeEventListener("popstate", syncStateFromUrl);
  }, [defaultPageSize, initialPage, initialSearch]);

  useEffect(() => {
    return () => {
      if (rowClickTimeoutRef.current !== null) window.clearTimeout(rowClickTimeoutRef.current);
    };
  }, []);

  // URL sync
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const prev = previousUrlStateRef.current;
    const searchChanged = prev.search !== debouncedSearchValue;
    const pageChanged = prev.page !== safeCurrentPage;
    const pageSizeChanged = prev.pageSize !== safePageSize;
    const sortFieldChanged = prev.sortField !== sortField;
    const sortDirChanged = prev.sortDir !== sortDir;

    if (!searchChanged && !pageChanged && !pageSizeChanged && !sortFieldChanged && !sortDirChanged) return;

    const currentSearch = params.get("search") ?? "";
    const currentPageParam = Number.parseInt(params.get("page") ?? "1", 10) || 1;
    const currentPageSizeParam = parsePositiveInt(params.get("per_page"), defaultPageSize);
    const currentSortField = params.get("sort") ?? null;
    const currentSortDir = parseSortDir(params.get("dir"));

    if (
      currentSearch === debouncedSearchValue &&
      currentPageParam === safeCurrentPage &&
      currentPageSizeParam === safePageSize &&
      currentSortField === sortField &&
      currentSortDir === sortDir
    ) {
      previousUrlStateRef.current = { page: safeCurrentPage, search: debouncedSearchValue, pageSize: safePageSize, sortField, sortDir };
      return;
    }

    if (debouncedSearchValue) params.set("search", debouncedSearchValue); else params.delete("search");
    if (safeCurrentPage > 1) params.set("page", String(safeCurrentPage)); else params.delete("page");
    if (safePageSize !== defaultPageSize) params.set("per_page", String(safePageSize)); else params.delete("per_page");
    if (sortField) { params.set("sort", sortField); if (sortDir === "desc") params.set("dir", "desc"); else params.delete("dir"); } else { params.delete("sort"); params.delete("dir"); }

    const query = params.toString();
    const nextUrl = query ? `${pathname}?${query}` : pathname;

    if (searchChanged || pageSizeChanged || sortFieldChanged || sortDirChanged) {
      window.history.replaceState(null, "", nextUrl);
    } else {
      window.history.pushState(null, "", nextUrl);
    }

    previousUrlStateRef.current = { page: safeCurrentPage, search: debouncedSearchValue, pageSize: safePageSize, sortField, sortDir };
  }, [safeCurrentPage, debouncedSearchValue, defaultPageSize, safePageSize, pathname, sortField, sortDir]);

  const table = useReactTable({
    data: data.results ?? [],
    columns,
    getCoreRowModel: getCoreRowModel(),
    onSortingChange: setSorting,
    state: { sorting },
    manualPagination: true,
    manualSorting: true,
    rowCount: data.total ?? 0,
  });

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

  return (
    <div className="rounded-xl border border-border/50 bg-card/50 overflow-hidden">
      {/* ── TOOLBAR: search + actions + record count ───── */}
      <div className="flex items-center justify-between gap-3 border-b border-border/40 px-4 py-2.5">
        <div className="flex items-center gap-3 flex-1 min-w-0">
          {/* Search */}
          <div className="relative w-full max-w-xs">
            <Label htmlFor="admin-table-search" className="sr-only">{searchPlaceholder}</Label>
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              id="admin-table-search"
              aria-label={searchPlaceholder}
              autoComplete="off"
              className="h-9 border-border bg-muted/30 pl-9 text-sm placeholder:text-muted-foreground/60 focus-visible:ring-1 focus-visible:ring-ring focus-visible:border-ring"
              name="admin-table-search"
              placeholder={searchPlaceholder}
              value={searchValue}
              onChange={(event) => setSearchValue(event.target.value)}
            />
          </div>

          {/* Record count + loading indicator */}
          <div className="flex items-center gap-2 text-[12px] text-muted-foreground/60 shrink-0">
            {isRefreshing && <LoaderCircle className="size-3 animate-spin" />}
            {safeTotal > 0 && <span>{safeTotal} records</span>}
          </div>
        </div>

        {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
      </div>

      {/* ── TABLE ───────────────────────────────────────── */}
      <div className="overflow-x-auto">
        <Table className="min-w-full border-separate border-spacing-0">
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent">
                {headerGroup.headers.map((header, index) => {
                  const isActionColumn = header.column.id === ADMIN_ACTION_COLUMN_ID;
                  const isFirstColumn = index === 0;
                  const isLastColumn = index === headerGroup.headers.length - 1;
                  const canSort = header.column.getCanSort();
                  const sorted = header.column.getIsSorted();

                  return (
                    <TableHead
                      key={header.id}
                      className={cn(
                        "h-9 border-b border-border/40 bg-muted/20 text-[11px] font-medium text-muted-foreground/70",
                        isFirstColumn && "pl-4",
                        isLastColumn && "pr-4",
                        isActionColumn ? "text-right" : "text-left",
                      )}
                      style={getColumnStyle(header.column)}
                    >
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className={cn(
                            "inline-flex items-center gap-1 rounded transition-colors hover:text-foreground",
                            sorted ? "text-foreground" : "text-muted-foreground/70",
                          )}
                        >
                          {flexRender(header.column.columnDef.header, header.getContext())}
                          {sorted === "asc" ? (
                            <ArrowUp className="size-3 shrink-0" />
                          ) : sorted === "desc" ? (
                            <ArrowDown className="size-3 shrink-0" />
                          ) : (
                            <ArrowUpDown className="size-3 shrink-0 opacity-30" />
                          )}
                        </button>
                      ) : (
                        flexRender(header.column.columnDef.header, header.getContext())
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows?.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow
                  key={row.id}
                  data-state={row.getIsSelected() && "selected"}
                  className={cn(
                    "group border-b border-border/30 transition-colors hover:bg-accent/20 data-[state=selected]:bg-accent/30",
                    hasRowAction && "cursor-pointer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring/50 focus-visible:ring-inset",
                  )}
                  onClick={(event) => handleRowClick(event, row)}
                  onDoubleClick={(event) => handleRowDoubleClick(event, row)}
                  onKeyDown={(event) => handleRowKeyDown(event, row)}
                  tabIndex={onRowClick ? 0 : undefined}
                >
                  {row.getVisibleCells().map((cell, index) => {
                    const isActionColumn = cell.column.id === ADMIN_ACTION_COLUMN_ID;
                    const isFirstColumn = index === 0;
                    const isLastColumn = index === row.getVisibleCells().length - 1;

                    return (
                      <TableCell
                        key={cell.id}
                        className={cn(
                          "py-2.5 text-[13px]",
                          isFirstColumn && "pl-4 text-muted-foreground",
                          isLastColumn && "pr-4",
                          isActionColumn && "whitespace-nowrap text-right",
                        )}
                        style={getColumnStyle(cell.column)}
                      >
                        {isActionColumn ? (
                          <div className="flex w-full items-center justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                            {flexRender(cell.column.columnDef.cell, cell.getContext())}
                          </div>
                        ) : (
                          flexRender(cell.column.columnDef.cell, cell.getContext())
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-32 text-center">
                  <div className="flex flex-col items-center justify-center gap-2">
                    <CircleMinus className="size-5 text-muted-foreground/40" />
                    <p className="text-[13px] text-muted-foreground">{emptyMessage}</p>
                    {searchValue && (
                      <p className="text-[12px] text-muted-foreground/50">Try a broader search or clear the filter.</p>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {/* ── FOOTER: pagination ─────────────────────────── */}
      {safeTotal > 0 && (
        <div className="flex items-center justify-between gap-3 border-t border-border/40 px-4 py-2">
          <div className="flex items-center gap-3 text-[13px] text-muted-foreground">
            <span>{rangeStart}–{rangeEnd} of {safeTotal}</span>
            <div className="flex items-center gap-1.5">
              <span>Rows</span>
              <Select value={String(effectivePageSize)} onValueChange={(v) => handlePageSizeChange(Number(v))}>
                <SelectTrigger className="h-8 w-auto gap-1 border-border bg-muted/30 px-2.5 text-[13px] text-muted-foreground">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {availablePageSizeOptions.map((opt) => (
                    <SelectItem key={opt} value={String(opt)} className="text-[12px]">{opt}</SelectItem>
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
              <ChevronLeft className="size-4" />
            </button>

            {(() => {
              const pages: React.ReactNode[] = [];
              const maxVisible = 5;

              if (totalPageCount <= maxVisible) {
                for (let i = 1; i <= totalPageCount; i++) {
                  pages.push(
                    <button
                      key={i}
                      onClick={() => setCurrentPage(i)}
                      className={cn(
                        "flex size-7 items-center justify-center rounded-md text-[12px] transition-colors",
                        safeCurrentPage === i
                          ? "bg-primary text-primary-foreground font-medium"
                          : "text-muted-foreground hover:bg-accent/30 hover:text-foreground",
                      )}
                    >
                      {i}
                    </button>,
                  );
                }
              } else {
                const addPage = (i: number) => {
                  pages.push(
                    <button
                      key={i}
                      onClick={() => setCurrentPage(i)}
                      className={cn(
                        "flex size-7 items-center justify-center rounded-md text-[12px] transition-colors",
                        safeCurrentPage === i
                          ? "bg-primary text-primary-foreground font-medium"
                          : "text-muted-foreground hover:bg-accent/30 hover:text-foreground",
                      )}
                    >
                      {i}
                    </button>,
                  );
                };

                addPage(1);
                if (safeCurrentPage > 3) pages.push(<span key="e1" className="flex size-7 items-center justify-center text-[12px] text-muted-foreground/40">...</span>);
                const start = Math.max(2, safeCurrentPage - 1);
                const end = Math.min(totalPageCount - 1, safeCurrentPage + 1);
                for (let i = start; i <= end; i++) addPage(i);
                if (safeCurrentPage < totalPageCount - 2) pages.push(<span key="e2" className="flex size-7 items-center justify-center text-[12px] text-muted-foreground/40">...</span>);
                addPage(totalPageCount);
              }

              return pages;
            })()}

            <button
              onClick={() => setCurrentPage(Math.min(safeCurrentPage + 1, totalPageCount))}
              disabled={safeCurrentPage >= totalPageCount}
              className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent/30 hover:text-foreground disabled:opacity-30 disabled:pointer-events-none"
              aria-label="Next page"
            >
              <ChevronRight className="size-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
