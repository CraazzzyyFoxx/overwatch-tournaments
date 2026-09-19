"use client";

import { useCallback } from "react";

import type { AdminTableFilters } from "@/components/data-table";
import { useQueryParams } from "@/hooks/useQueryParams";

export interface FilterOption {
  value: string;
  label: string;
  /** How many rows match, when the endpoint reports facet counts. */
  count?: number;
}

export type FilterDef =
  | { key: string; label: string; kind: "single"; options: FilterOption[] }
  | { key: string; label: string; kind: "multi"; options: FilterOption[] }
  /** Boolean chip: present in the URL as `1`, absent otherwise. */
  | { key: string; label: string; kind: "toggle" }
  /** Server-searched value (tournament, team, player) — the URL keeps its id. */
  | {
      key: string;
      label: string;
      kind: "entity";
      search: (query: string) => Promise<FilterOption[]>;
    };

export type FilterValue = string | string[] | boolean;

export interface AdminFilters {
  /** Every declared key, at its empty default when the filter is off. */
  values: Record<string, FilterValue>;
  set: (key: string, value: FilterValue | null) => void;
  /**
   * One URL write for several keys.
   *
   * `set` reads the query string from the render it was created in, so N
   * sequential `set` calls all start from the same snapshot and only the last
   * one survives — which is every preset and every "clear these three".
   */
  setMany: (values: Record<string, FilterValue | null>) => void;
  clear: () => void;
  toTableFilters: () => AdminTableFilters;
  /** Opaque identity of the active set, for `AdminDataTable`'s `filterKey`. */
  filterKey: string;
}

const MULTI_SEPARATOR = ",";

function readValue(def: FilterDef, params: URLSearchParams): FilterValue {
  const raw = params.get(def.key) ?? "";
  if (def.kind === "toggle") return raw === "1";
  if (def.kind === "multi") return raw ? raw.split(MULTI_SEPARATOR).filter(Boolean) : [];
  return raw;
}

/** URL form of a value, or `null` when the filter is off and the param goes. */
function writeValue(value: FilterValue | null): string | null {
  if (value === null || value === false || value === "") return null;
  if (value === true) return "1";
  if (Array.isArray(value)) return value.length > 0 ? value.join(MULTI_SEPARATOR) : null;
  return value;
}

export function isFilterActive(value: FilterValue | undefined): boolean {
  if (value === undefined) return false;
  if (Array.isArray(value)) return value.length > 0;
  return value !== "" && value !== false;
}

/**
 * URL-backed filter state for a T2 browser.
 *
 * The query string is the only store: a chip written here survives a reload
 * and travels in a link, which is the contract every admin screen is held to.
 * Changing any filter drops `page` and `id` — narrowing while on page 4 or
 * with row 8812 open otherwise strands the user on a page that no longer
 * exists, or an inspector for a row the new filter excludes.
 */
export function useAdminFilters(defs: FilterDef[]): AdminFilters {
  const { searchParams, setParams } = useQueryParams({ resetOnChange: ["page", "id"] });

  const search = searchParams?.toString() ?? "";

  // Read straight from `defs` every render rather than through a memo. Callers
  // build their option lists inline, so `defs` is a fresh array on every pass
  // and any memo keyed on it would miss anyway; parsing a handful of query
  // params is cheaper than the bookkeeping. Nothing downstream holds these
  // identities — `filterKey` is a string, and `AdminDataTable` compares the
  // table filters serialised.
  const params = new URLSearchParams(search);
  const values = Object.fromEntries(
    defs.map((def) => [def.key, readValue(def, params)])
  ) as Record<string, FilterValue>;

  // The two writers are the exception: `AdminAuditPage` lists them as column
  // memo dependencies precisely because the `filters` object around them is
  // rebuilt every render. They close over nothing but `setParams`.
  const set = useCallback(
    (key: string, value: FilterValue | null) => setParams({ [key]: writeValue(value) }),
    [setParams]
  );

  const setMany = useCallback(
    (next: Record<string, FilterValue | null>) =>
      setParams(
        Object.fromEntries(Object.entries(next).map(([key, value]) => [key, writeValue(value)]))
      ),
    [setParams]
  );

  const clear = () => {
    if (defs.length === 0) return;
    setParams(Object.fromEntries(defs.map((def) => [def.key, null])));
  };

  const toTableFilters = (): AdminTableFilters => {
    const out: AdminTableFilters = {};
    for (const def of defs) {
      const value = values[def.key];
      if (!isFilterActive(value)) continue;
      out[def.key] = Array.isArray(value) ? value : [value === true ? "1" : String(value)];
    }
    return out;
  };

  const filterKey = Object.entries(values)
    .filter(([, value]) => isFilterActive(value))
    .map(
      ([key, value]) =>
        `${key}=${Array.isArray(value) ? value.join(MULTI_SEPARATOR) : String(value)}`
    )
    .sort()
    .join("&");

  return { values, set, setMany, clear, toTableFilters, filterKey };
}
