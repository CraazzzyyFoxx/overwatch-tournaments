import { PaginatedResponse } from "@/types/pagination.types";

export function paginateResults<T>(items: T[], page: number, perPage: number): PaginatedResponse<T> {
  const startIndex = (page - 1) * perPage;
  return {
    page,
    per_page: perPage,
    total: items.length,
    results: items.slice(startIndex, startIndex + perPage),
  };
}

export function sortArray<T>(arr: T[], field: string | null, dir: "asc" | "desc"): T[] {
  if (!field) return arr;
  return [...arr].sort((a, b) => {
    const aVal = (a as Record<string, unknown>)[field];
    const bVal = (b as Record<string, unknown>)[field];
    if (aVal == null && bVal == null) return 0;
    if (aVal == null) return dir === "asc" ? 1 : -1;
    if (bVal == null) return dir === "asc" ? -1 : 1;
    let cmp: number;
    if (typeof aVal === "string" && typeof bVal === "string") {
      cmp = aVal.localeCompare(bVal);
    } else {
      cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0;
    }
    return dir === "asc" ? cmp : -cmp;
  });
}
