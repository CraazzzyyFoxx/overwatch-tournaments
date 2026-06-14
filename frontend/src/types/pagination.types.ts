export interface PaginatedResponse<T> {
  page: number;
  per_page: number;
  total: number;
  results: T[];
}

export interface LookupItem {
  id: number;
  name: string;
}

export enum SortDirection {
  asc = "asc",
  desc = "desc"
}

export const sortDirectionAntd = {
  ascend: SortDirection.asc,
  descend: SortDirection.desc
};

export interface PaginationParams {
  page: number | undefined;
  per_page: number | undefined;
  sort: string;
  order: SortDirection;
  entities: string[];
}

export interface SearchPaginationParams extends PaginationParams {
  query: string | null;
  fields: string[];
}
