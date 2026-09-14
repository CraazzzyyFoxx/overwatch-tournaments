import type { ColumnDef } from "@tanstack/react-table";

/** One selectable value of a column filter. */
export interface AdminColumnFilterOption {
  value: string;
  label: string;
}

/**
 * A filter declared on the column whose values it narrows.
 *
 * `param` is the real query parameter the endpoint understands (`status`,
 * `has_logs`, …) — the table never invents one, because admin list endpoints
 * take typed params, not a generic filter DSL. In client mode the same
 * declaration is how a URL param is matched onto a column's `filterFn`.
 *
 * The control that WRITES it is `kit/AdminFilterBar`, above the table; this
 * is only the endpoint contract, so it carries no presentation.
 */
export interface AdminColumnFilterSpec {
  param: string;
  /**
   * `single` (default) sends one value — what every current admin endpoint
   * takes, since its filter params are scalars. `multi` sends each checked
   * value as a repeated param, for endpoints whose param is a list.
   */
  mode?: "single" | "multi";
  options: readonly AdminColumnFilterOption[];
}

export function readAdminColumnFilter(meta: unknown): AdminColumnFilterSpec | undefined {
  const spec = (meta as { filter?: AdminColumnFilterSpec } | undefined)?.filter;
  return spec && spec.param ? spec : undefined;
}

/** Checked values per query param. An absent or empty entry means "no filter". */
export type AdminTableFilters = Record<string, string[]>;

export function collectFilterSpecs<TData>(
  columns: readonly ColumnDef<TData>[]
): AdminColumnFilterSpec[] {
  const specs: AdminColumnFilterSpec[] = [];
  for (const column of columns) {
    const spec = readAdminColumnFilter(column.meta);
    if (spec) specs.push(spec);
  }
  return specs;
}

export function parseFiltersFromParams(
  specs: readonly AdminColumnFilterSpec[],
  params: URLSearchParams
): AdminTableFilters {
  const filters: AdminTableFilters = {};
  for (const spec of specs) {
    // A catalogue-backed filter (roles, gamemodes) has no options on the first
    // render, and the URL is read once on mount. Validating against an empty
    // option set there would drop `?role=support` from every deep link and
    // reload, so an option-less spec takes the URL at its word — the endpoint
    // validates it anyway.
    const allowed = new Set(spec.options.map((option) => option.value));
    const raw = params.getAll(spec.param);
    const values = allowed.size === 0 ? raw : raw.filter((value) => allowed.has(value));
    if (values.length === 0) continue;
    filters[spec.param] = spec.mode === "multi" ? values : [values[0]];
  }
  return filters;
}

/** Rewrites every declared filter param in place, dropping the cleared ones. */
export function writeFiltersToParams(
  specs: readonly AdminColumnFilterSpec[],
  filters: AdminTableFilters,
  params: URLSearchParams
): void {
  for (const spec of specs) {
    params.delete(spec.param);
    for (const value of filters[spec.param] ?? []) {
      params.append(spec.param, value);
    }
  }
}

/**
 * Stable string identity of a filter set, so the table can compare "did the
 * filters change" with one `!==` instead of a per-param ref for each column.
 */
export function serializeFilters(filters: AdminTableFilters): string {
  return Object.keys(filters)
    .filter((param) => (filters[param]?.length ?? 0) > 0)
    .sort()
    .map((param) => `${param}=${[...filters[param]].sort().join(",")}`)
    .join("&");
}
