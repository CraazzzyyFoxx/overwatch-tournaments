import { PaginatedResponse } from "@/types/pagination.types";

export function normalizePaginatedResponse<T>(
  response: PaginatedResponse<T>
): PaginatedResponse<T> {
  const results = Array.isArray(response.results) ? response.results : [];
  const total = Number.isFinite(response.total) && response.total >= 0 ? response.total : results.length;
  const page = Number.isFinite(response.page) && response.page > 0 ? response.page : 1;
  const perPage =
    Number.isFinite(response.per_page) && response.per_page > 0
      ? response.per_page
      : total > 0
        ? results.length || total
        : 0;

  return {
    ...response,
    results,
    total,
    page,
    per_page: perPage,
  };
}
