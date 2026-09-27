"use client";

import { useEffect, useRef, useState } from "react";
import type { ColumnDef, SortingState } from "@tanstack/react-table";
import { useDebounce } from "use-debounce";

import type { SortDir } from "@/components/data-table/types";
import {
  collectFilterSpecs,
  parseFiltersFromParams,
  serializeFilters,
  writeFiltersToParams,
  type AdminTableFilters
} from "@/components/data-table/filters";
import {
  parsePositiveInt,
  parseSorting,
  serializeSorting,
  writeSorting
} from "@/components/data-table/url-state";

export interface AdminTableStateOptions<TData> {
  columns: ColumnDef<TData>[];
  pathname: string;
  initialPageSize: number;
  initialSort?: { field: string; dir: SortDir };
  filterKey?: string;
  filters?: AdminTableFilters;
  onFiltersChange?: (next: AdminTableFilters) => void;
}

/**
 * Page, search, page size, sort and column filters — the state the URL owns.
 *
 * Every piece of it is mirrored into the query string and restored from it
 * (including back/forward), and every narrowing change resets to page 1.
 */
export function useAdminTableState<TData>({
  columns,
  pathname,
  initialPageSize,
  initialSort,
  filterKey,
  filters: controlledFilters,
  onFiltersChange
}: AdminTableStateOptions<TData>) {
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
  // Written in an effect declared before those, so their first run already
  // sees the specs of the render that mounted them.
  const filterSpecsRef = useRef(filterSpecs);
  useEffect(() => { filterSpecsRef.current = filterSpecs; });
  const serializedFilters = serializeFilters(filters);
  // Server mode sorts by one column: the backend takes a single `sort_by`.
  const sortField = sorting[0]?.id ?? null;
  const sortDir: SortDir = sorting[0]?.desc ? "desc" : "asc";
  const sortKey = serializeSorting(sorting);
  const previousDebouncedSearchRef = useRef("");
  const previousPageSizeRef = useRef(initialPageSize);
  const previousFilterKeyRef = useRef(filterKey);
  const previousSortRef = useRef("");
  const previousFiltersRef = useRef("");
  const previousUrlStateRef = useRef({ page: 1, search: "", pageSize: initialPageSize, sortKey: "", filters: "" });
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

  /* eslint-disable react-hooks/set-state-in-effect -- Narrowing the result set (a new search, page size, sort, caller filter key or column filter) must land the user back on page 1; the change is only observable once the new value has rendered, so the reset is a follow-up commit by design. */
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
  /* eslint-enable react-hooks/set-state-in-effect */

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

  return {
    searchValue,
    setSearchValue,
    debouncedSearchValue,
    currentPage: safeCurrentPage,
    setCurrentPage,
    pageSize: safePageSize,
    setPageSize,
    sorting,
    setSorting,
    sortField,
    sortDir,
    filters,
    setFilters,
    serializedFilters
  };
}
