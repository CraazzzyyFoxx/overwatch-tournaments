"use client";

import { useCallback, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useDebounce } from "use-debounce";

export interface SearchComboboxMessages {
  /** Shown while the query is in flight. */
  loading: string;
  /** Shown when the query errors. */
  error: string;
  /** Shown before the minimum query length is reached. */
  minChars: string;
  /** Shown when the query succeeds with zero matches. */
  empty: string;
}

export interface UseSearchComboboxQueryOptions<TItem, TSelected> {
  /** react-query key prefix; the debounced/trimmed search term is appended. */
  queryKeyPrefix: unknown[];
  /** Fetches results for the debounced/trimmed search term. */
  fetchResults: (params: { query: string; signal: AbortSignal }) => Promise<TItem[]>;
  /** The combobox's own `onSelect` prop — invoked, then the popover resets. */
  onSelect: (item: TSelected | undefined) => void;
  /** Row-count-independent messages for the `<CommandEmpty>` row. */
  messages: SearchComboboxMessages;
  /** Minimum trimmed-query length before searching. Defaults to 2. */
  minQueryLength?: number;
  /** Debounce delay, in ms, applied to the raw input value. Defaults to 250. */
  debounceMs?: number;
  /** react-query `staleTime`, in ms. Defaults to 60s. */
  staleTime?: number;
}

/**
 * Open/search-value/debounce/query/select scaffolding shared by every
 * server-searched admin combobox (`AuthUserSearchCombobox`,
 * `UserSearchCombobox`). Callers own the `<AdminCombobox>` shell, the row
 * rendering, and any selection-shape mapping; this hook owns the plumbing
 * that reaches the server.
 */
export function useSearchComboboxQuery<TItem, TSelected>({
  queryKeyPrefix,
  fetchResults,
  onSelect,
  messages,
  minQueryLength = 2,
  debounceMs = 250,
  staleTime = 60 * 1000
}: UseSearchComboboxQueryOptions<TItem, TSelected>) {
  const [open, setOpen] = useState(false);
  const [searchValue, setSearchValue] = useState("");
  const [debouncedSearch] = useDebounce(searchValue, debounceMs);

  const normalizedQuery = debouncedSearch.trim();
  const shouldSearch = normalizedQuery.length >= minQueryLength;

  const resultsQuery = useQuery({
    queryKey: [...queryKeyPrefix, normalizedQuery],
    enabled: open && shouldSearch,
    queryFn: ({ signal }) => fetchResults({ query: normalizedQuery, signal }),
    staleTime
  });

  const results = resultsQuery.data ?? [];

  const handleSelect = useCallback(
    (item: TSelected | undefined) => {
      onSelect(item);
      setOpen(false);
      setSearchValue("");
    },
    [onSelect]
  );

  const emptyMessage = resultsQuery.isFetching
    ? messages.loading
    : resultsQuery.isError
      ? messages.error
      : !shouldSearch
        ? messages.minChars
        : messages.empty;

  return {
    open,
    setOpen,
    searchValue,
    setSearchValue,
    results,
    shouldSearch,
    handleSelect,
    emptyMessage
  };
}
