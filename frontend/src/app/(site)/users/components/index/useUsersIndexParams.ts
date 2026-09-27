"use client";

import { useCallback, useEffect, useState } from "react";
import { useDebounce } from "use-debounce";

import { useQueryParams } from "@/hooks/useQueryParams";
import { useDivisionGrid } from "@/hooks/useCurrentWorkspace";
import { clampDivisionToGrid } from "@/lib/divisions/grid";
import { parseOptionalInt, parsePositiveInt } from "@/app/(site)/users/components/shared/list-utils";
import type { UserRoleType } from "@/types/user.types";

import { parseOrder, parseSort, parseView, type OrderValue, type SortValue, type ViewMode } from "./users-index.model";

export interface UsersIndexParams {
  page: number;
  perPage: number;
  query: string;
  sort: SortValue;
  order: OrderValue;
  view: ViewMode;
  role: UserRoleType | undefined;
  divMin: number | undefined;
  divMax: number | undefined;
  letter: string | undefined;
}

export interface UsersIndexParamControls {
  params: UsersIndexParams;
  /** Live search box value; the URL only follows it once typing settles. */
  searchInput: string;
  setSearchInput: (value: string) => void;
  setRole: (value: "all" | UserRoleType) => void;
  setDivMin: (value: string) => void;
  setDivMax: (value: string) => void;
  setSort: (value: SortValue) => void;
  setOrder: (value: OrderValue) => void;
  setView: (value: ViewMode) => void;
  setLetter: (value: string | null) => void;
  setPage: (value: number) => void;
}

/**
 * The users index keeps every filter in the URL, so a link reproduces the
 * screen. `useQueryParams` already resets `page` whenever any other param
 * changes, so paging passes only `page` and is left alone.
 */
export function useUsersIndexParams(): UsersIndexParamControls {
  const { searchParams, setParams } = useQueryParams();
  const divisionGrid = useDivisionGrid();

  const query = searchParams?.get("query") ?? "";
  const params: UsersIndexParams = {
    page: parsePositiveInt(searchParams?.get("page") ?? null, 1),
    perPage: parsePositiveInt(searchParams?.get("per_page") ?? null, 20),
    query,
    sort: parseSort(searchParams?.get("sort") ?? null),
    order: parseOrder(searchParams?.get("order") ?? null),
    view: parseView(searchParams?.get("view") ?? null),
    role: (searchParams?.get("role") as UserRoleType | null) ?? undefined,
    divMin: clampDivisionToGrid(divisionGrid, parseOptionalInt(searchParams?.get("div_min") ?? null)),
    divMax: clampDivisionToGrid(divisionGrid, parseOptionalInt(searchParams?.get("div_max") ?? null)),
    letter: searchParams?.get("letter") ?? undefined
  };

  const [searchInput, setSearchInput] = useState(query);
  const [debouncedSearch] = useDebounce(searchInput, 300);

  useEffect(() => {
    setSearchInput(query);
  }, [query]);

  useEffect(() => {
    const normalizedInput = debouncedSearch.trim();
    const normalizedQuery = query.trim();
    if (normalizedInput === normalizedQuery) return;
    setParams({ query: normalizedInput || undefined });
  }, [debouncedSearch, query, setParams]);

  const setDivision = useCallback(
    (key: "div_min" | "div_max", value: string) => {
      setParams({
        [key]:
          value === "all" ? undefined : clampDivisionToGrid(divisionGrid, parseOptionalInt(value))
      });
    },
    [divisionGrid, setParams]
  );

  return {
    params,
    searchInput,
    setSearchInput,
    setRole: (value) => setParams({ role: value === "all" ? undefined : value }),
    setDivMin: (value) => setDivision("div_min", value),
    setDivMax: (value) => setDivision("div_max", value),
    setSort: (value) => setParams({ sort: value }),
    setOrder: (value) => setParams({ order: value }),
    setView: (value) => setParams({ view: value === "analytics" ? undefined : value }),
    setLetter: (value) => setParams({ letter: value === null ? undefined : value }),
    setPage: (value) => setParams({ page: value })
  };
}
