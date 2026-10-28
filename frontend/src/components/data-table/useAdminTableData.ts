"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { readColumnMeta } from "@/components/data-table/columns";
import type { AdminTableFilters } from "@/components/data-table/filters";
import type { DataTableProps, PaginatedResponse, SortDir } from "@/components/data-table/types";

export interface AdminTableDataOptions<TData>
  extends Pick<DataTableProps<TData>, "queryKey" | "queryFn" | "rows" | "columns"> {
  isClientMode: boolean;
  isLoading: boolean;
  page: number;
  search: string;
  pageSize: number;
  /** Server mode: the page size is final; a fitted table holds its first request until it has measured. */
  pageSizeReady: boolean;
  sortField: string | null;
  sortDir: SortDir;
  filters: AdminTableFilters;
}

/** One instance, so a loading table's "no rows yet" keeps its identity across renders. */
const EMPTY_RESULTS: never[] = [];

/**
 * The two data modes behind one shape: server mode runs the caller's query for
 * the current page, client mode narrows the rows it was handed.
 */
export function useAdminTableData<TData>({
  queryKey,
  queryFn,
  rows,
  columns,
  isClientMode,
  isLoading,
  page,
  search,
  pageSize,
  pageSizeReady,
  sortField,
  sortDir,
  filters
}: AdminTableDataOptions<TData>) {
  const dataQuery = useQuery({
    queryKey: queryKey
      ? queryKey(page, search, pageSize, sortField, sortDir, filters)
      : ["admin-data-table", "client-mode"],
    queryFn: queryFn
      ? () => queryFn(page, search, pageSize, sortField, sortDir, filters)
      : () => Promise.resolve({ results: [] as TData[], total: 0, page: 1, per_page: pageSize }),
    enabled: !isClientMode && pageSizeReady,
    placeholderData: (previousData) => previousData,
  });

  // Client mode does its own searching, so the search box narrows the rows
  // here instead of turning into a query param. A column opts in by declaring
  // `meta.searchValue`; a column of badges has no useful text to match.
  const clientRows = useMemo(() => {
    if (!rows) return [];
    const needle = search.trim().toLowerCase();
    if (!needle) return rows;
    const searchableColumns = columns.filter((column) => readColumnMeta<TData>(column.meta).searchValue);
    return rows.filter((row) =>
      searchableColumns.some((column) => {
        const value = readColumnMeta<TData>(column.meta).searchValue?.(row);
        return value ? value.toLowerCase().includes(needle) : false;
      })
    );
  }, [rows, search, columns]);

  // One object per query result: `onPageRowsChange` hands it on from an effect keyed on it.
  const data = useMemo<PaginatedResponse<TData>>(
    () => dataQuery.data ?? { results: EMPTY_RESULTS, total: 0, page: 1, per_page: pageSize },
    [dataQuery.data, pageSize]
  );

  return {
    data,
    clientRows,
    /** No rows have ever been shown: the body draws a skeleton, not the empty state. Pending covers a request still held for the page size. */
    isInitialLoading: isClientMode ? isLoading : dataQuery.isPending,
    /** A refetch behind an already-rendered page, or the caller's own client-mode fetch. */
    isRefreshing: isClientMode ? isLoading : dataQuery.isFetching && !dataQuery.isLoading
  };
}
