import { apiFetch } from "@/lib/api/fetch";
import { LookupItem, PaginatedResponse } from "@/types/pagination.types";
import { MapRead } from "@/types/map.types";

export default class mapService {
  static async lookup(): Promise<LookupItem[]> {
    return apiFetch("/api/v1/maps/lookup").then((res) => res.json());
  }

  /**
   * `entities` maps to the backend's relationship-loading tokens. The gamemode
   * relation is only eager-loaded and serialized when `"gamemode"` is requested;
   * omit it and every `MapRead.gamemode` comes back null.
   */
  static async getAll({
    page = 1,
    perPage = -1,
    sort = "name",
    order = "asc",
    query,
    entities
  }: {
    page?: number;
    perPage?: number;
    sort?: "id" | "name" | "gamemode_id";
    order?: "asc" | "desc";
    query?: string;
    entities?: "gamemode"[];
  } = {}): Promise<PaginatedResponse<MapRead>> {
    return apiFetch("/api/v1/maps", {
      query: {
        page,
        per_page: perPage,
        sort,
        order,
        query,
        fields: ["name"],
        entities
      }
    }).then((res) => res.json());
  }
}
