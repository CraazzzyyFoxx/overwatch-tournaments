/** One page of a server-mode query. Structurally matches the API's paginated envelope. */
export interface PaginatedResponse<T> {
  page: number;
  per_page: number;
  total: number;
  results: T[];
}

export type SortDir = "asc" | "desc";

/** `aria-sort` for a sortable header from TanStack's `getIsSorted()`; non-sortable headers omit the attribute. */
export function ariaSortValue(direction: "asc" | "desc" | false): "ascending" | "descending" | "none" {
  if (direction === "asc") return "ascending";
  if (direction === "desc") return "descending";
  return "none";
}
