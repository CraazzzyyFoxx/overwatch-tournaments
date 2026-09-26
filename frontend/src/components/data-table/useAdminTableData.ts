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
  sortField: string | null;
  sortDir: SortDir;
  filters: AdminTableFilters;
}

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
    enabled: !isClientMode,
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

  const data: PaginatedResponse<TData> = dataQuery.data ?? { results: [], total: 0, page: 1, per_page: pageSize };

  return {
    data,
    clientRows,
    /** A refetch behind an already-rendered page, or the caller's own client-mode fetch. */
    isRefreshing: isClientMode ? isLoading : dataQuery.isFetching && !dataQuery.isLoading
  };
}
