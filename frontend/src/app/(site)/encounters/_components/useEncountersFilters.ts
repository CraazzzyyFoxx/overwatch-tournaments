"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { useDebounce } from "use-debounce";

import {
  DEFAULT_FILTERS,
  filtersToSearchParams,
  type EncounterFilterState
} from "./encounters.helpers";

export interface EncountersFilterControls {
  /** Raw (undebounced) filter state — what the controls are bound to. */
  filters: EncounterFilterState;
  /** `filters` with the debounced search term folded in — what the queries read. */
  effectiveFilters: EncounterFilterState;
  searchValue: string;
  page: number;
  setPage: (page: number) => void;
  setSearchValue: (value: string) => void;
  /** Patch a few fields and return to page 1. */
  patchFilters: (patch: Partial<EncounterFilterState>) => void;
  /** Replace the whole filter state (built-in view, saved view) and return to page 1. */
  applyFilters: (next: EncounterFilterState) => void;
  clearFilters: () => void;
}

/**
 * Filter/search/page state for the encounters index, mirrored into the URL.
 *
 * The mirror is a `replaceState`, not a router navigation: the page re-renders
 * off the query cache either way, and a push would stack one history entry per
 * keystroke. The previous-value ref keeps the very first render (which already
 * matches the server-rendered URL) from writing a redundant entry.
 */
export function useEncountersFilters(
  initialFilters: EncounterFilterState,
  initialPage: number
): EncountersFilterControls {
  const pathname = usePathname();
  const [filters, setFilters] = useState<EncounterFilterState>(initialFilters);
  const [searchValue, setSearchInput] = useState(initialFilters.query);
  const [debouncedSearch] = useDebounce(searchValue, 300);
  const [page, setPage] = useState(initialPage);
  const previousUrlRef = useRef({ page: initialPage, filters: initialFilters });
  const effectiveFilters = useMemo(
    () => ({ ...filters, query: debouncedSearch }),
    [debouncedSearch, filters]
  );

  useEffect(() => {
    const params = filtersToSearchParams(effectiveFilters, page);
    const nextUrl = params.toString() ? `${pathname}?${params.toString()}` : pathname;
    const previous = previousUrlRef.current;
    if (
      previous.page === page &&
      JSON.stringify(previous.filters) === JSON.stringify(effectiveFilters)
    ) {
      return;
    }

    window.history.replaceState(null, "", nextUrl);
    previousUrlRef.current = { page, filters: effectiveFilters };
  }, [effectiveFilters, page, pathname]);

  return {
    filters,
    effectiveFilters,
    searchValue,
    page,
    setPage,
    setSearchValue: (value) => {
      setPage(1);
      setSearchInput(value);
    },
    patchFilters: (patch) => {
      setPage(1);
      setFilters((current) => ({ ...current, ...patch }));
    },
    applyFilters: (next) => {
      setPage(1);
      setSearchInput(next.query);
      setFilters(next);
    },
    clearFilters: () => {
      setSearchInput("");
      setPage(1);
      setFilters(DEFAULT_FILTERS);
    }
  };
}
