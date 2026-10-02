import { apiFetch } from "@/lib/api/fetch";
import type { ScrimCreateInput, ScrimListScope, ScrimRoom } from "@/types/scrim.types";

/** The share token is a path segment, so it is escaped rather than interpolated raw. */
function tokenPath(token: string): string {
  return `/api/v1/scrims/${encodeURIComponent(token)}`;
}

class ScrimService {
  async createRoom(data: ScrimCreateInput): Promise<ScrimRoom> {
    const response = await apiFetch("/api/v1/scrims", { method: "POST", body: data });
    return response.json();
  }

  /**
   * Rooms in a workspace. `scope` is "mine" (the caller's own, hosted or
   * captained) or "workspace" — every room there, which the server allows only
   * for staff holding `match.result`.
   */
  async listRooms(
    workspaceId: number | null,
    scope: ScrimListScope = "mine"
  ): Promise<{ rooms: ScrimRoom[] }> {
    const response = await apiFetch("/api/v1/scrims", {
      query: { workspace_id: workspaceId, scope }
    });
    return response.json();
  }

  /**
   * Fetch one room by its share token. `null` means the token names nothing the
   * caller may see — an unknown token and a room hidden from this viewer are one
   * outcome by design (`Tournament.is_hidden` answers both with a 404), so the
   * room page routes both to `notFound()`.
   */
  async getRoom(token: string): Promise<ScrimRoom | null> {
    const response = await apiFetch(tokenPath(token), { throwOnError: false });
    if (!response.ok) return null;
    return response.json();
  }

  /**
   * Take the room's open side. Idempotent and first-writer-wins server-side, so
   * two viewers racing the same link produce one captain and one plain spectator.
   */
  async claimSide(token: string): Promise<ScrimRoom> {
    const response = await apiFetch(`${tokenPath(token)}/claim`, { method: "POST" });
    return response.json();
  }

  /** Retires the room. History is kept: a closed room stays readable to its participants. */
  async closeRoom(token: string): Promise<ScrimRoom> {
    const response = await apiFetch(`${tokenPath(token)}/close`, { method: "POST" });
    return response.json();
  }
}

const scrimService = new ScrimService();
export default scrimService;
