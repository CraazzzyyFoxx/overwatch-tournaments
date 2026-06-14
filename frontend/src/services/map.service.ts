import { apiFetch } from "@/lib/api-fetch";
import { LookupItem, PaginatedResponse } from "@/types/pagination.types";
import { MapRead } from "@/types/map.types";

export default class mapService {
  static async lookup(): Promise<LookupItem[]> {
    return apiFetch("app", "maps/lookup").then((res) => res.json());
  }

  static async getAll({
    page = 1,
    perPage = -1,
    sort = "name",
    order = "asc",
    query
  }: {
    page?: number;
    perPage?: number;
    sort?: "id" | "name" | "gamemode_id";
    order?: "asc" | "desc";
    query?: string;
  } = {}): Promise<PaginatedResponse<MapRead>> {
    return apiFetch("app","maps", {
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"]
      }
    }).then((res) => res.json());
  }
}
