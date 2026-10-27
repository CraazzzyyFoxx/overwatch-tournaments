import { apiFetch } from "@/lib/api/fetch";
import type { PaginatedResponse } from "@/types/pagination.types";
import type { CatalogEntityRead, CatalogKind, CatalogListFilters } from "@/types/catalog.types";

interface RequestOptions {
  signal?: AbortSignal;
  /** Data Cache for a server read: the catalog is public and changes with a release, not between requests. */
  next?: { revalidate?: number | false };
}

/**
 * Native public catalog: one discipline's characters, maps or modes. The catalog is global per discipline, so the
 * request carries no workspace (`skipWorkspace`) — the discipline and kind in the path are the whole scope, and a
 * kind the game does not declare is a 404 the caller must not provoke (check `descriptor.kinds` first).
 */
export default class catalogService {
  static async list(
    discipline: string,
    kind: CatalogKind,
    filters: CatalogListFilters = {},
    { signal, next }: RequestOptions = {}
  ): Promise<PaginatedResponse<CatalogEntityRead>> {
    const { attrs, ...rest } = filters;
    return apiFetch(`/api/v1/catalog/${encodeURIComponent(discipline)}/${kind}`, {
      skipWorkspace: true,
      signal,
      next,
      query: { ...rest, ...(attrs !== undefined && { attrs: JSON.stringify(attrs) }) }
    }).then((res) => res.json());
  }

  /** Inactive rows are readable (a stored reference may point at one); the id must belong to this discipline and kind. */
  static async get(
    discipline: string,
    kind: CatalogKind,
    id: number,
    { signal }: RequestOptions = {}
  ): Promise<CatalogEntityRead> {
    return apiFetch(`/api/v1/catalog/${encodeURIComponent(discipline)}/${kind}/${id}`, {
      skipWorkspace: true,
      signal
    }).then((res) => res.json());
  }
}
