import { apiFetch } from "@/lib/api-fetch";
import type {
  DraftBoard,
  DraftFeasibility,
  DraftPickOptionsResponse,
  DraftRole,
  DraftRoleEditRequest,
  DraftRoleEditResponse,
  DraftSeedRequest,
  DraftSeedResponse,
  DraftSession,
  DraftSessionCreateRequest,
  DraftSuggestionsResponse
} from "@/types/draft.types";

export const draftEndpoints = {
  feasibility: (sessionId: number) => `/api/balancer/draft/sessions/${sessionId}/feasibility`,
  pickOptions: (pickId: number) => `/api/balancer/draft/picks/${pickId}/options`,
  playerRole: (sessionId: number, playerId: number) =>
    `/api/balancer/draft/sessions/${sessionId}/players/${playerId}/roles`
};

// All draft endpoints live on balancer-service under /api/balancer/draft/...
// Reads are public (spectating); writes use apiFetch's automatic bearer token.

// The `X | None` board read returns HTTP 200 with a `null` body from FastAPI,
// but the Go gateway omits the body for null data. Parse defensively so an empty
// body reads as `null` instead of throwing on `.json()`.
async function readJsonOrNull<T>(response: Response): Promise<T | null> {
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : null;
}

export default class draftService {
  static async getTournamentBoard(tournamentId: number): Promise<DraftBoard | null> {
    const res = await apiFetch(`/api/balancer/draft/tournaments/${tournamentId}/draft`);
    return readJsonOrNull<DraftBoard>(res);
  }

  static async getSessionBoard(sessionId: number): Promise<DraftBoard> {
    const res = await apiFetch(`/api/balancer/draft/sessions/${sessionId}/board`);
    return res.json();
  }

  static async getSession(sessionId: number): Promise<DraftSession> {
    const res = await apiFetch(`/api/balancer/draft/sessions/${sessionId}`);
    return res.json();
  }

  static async getSuggestions(sessionId: number): Promise<DraftSuggestionsResponse> {
    const res = await apiFetch(`/api/balancer/draft/sessions/${sessionId}/suggestions`);
    return res.json();
  }

  static async getFeasibility(sessionId: number): Promise<DraftFeasibility> {
    const res = await apiFetch(draftEndpoints.feasibility(sessionId));
    return res.json();
  }

  static async getPickOptions(pickId: number): Promise<DraftPickOptionsResponse> {
    const res = await apiFetch(draftEndpoints.pickOptions(pickId));
    return res.json();
  }

  static async editPlayerRole(
    sessionId: number,
    playerId: number,
    body: DraftRoleEditRequest
  ): Promise<DraftRoleEditResponse> {
    const res = await apiFetch(draftEndpoints.playerRole(sessionId, playerId), {
      method: "POST",
      body
    });
    return res.json();
  }

  // --- admin lifecycle (keyed by tournament_id) ---
  static async createSession(
    tournamentId: number,
    body: DraftSessionCreateRequest
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/balancer/draft/tournaments/${tournamentId}/sessions`, {
      method: "POST",
      body
    });
    return res.json();
  }

  static async seed(
    tournamentId: number,
    sessionId: number,
    body: DraftSeedRequest
  ): Promise<DraftSeedResponse> {
    const res = await apiFetch(`/api/balancer/draft/tournaments/${tournamentId}/sessions/${sessionId}/seed`,
      { method: "POST", body }
    );
    return res.json();
  }

  static async lifecycle(
    tournamentId: number,
    sessionId: number,
    action: "start" | "pause" | "resume" | "cancel" | "export" | "rollback"
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/balancer/draft/tournaments/${tournamentId}/sessions/${sessionId}/${action}`,
      { method: "POST" }
    );
    return res.json();
  }

  // --- pick actions (keyed by pick_id) ---
  static async select(
    pickId: number,
    body: { player_id: number; expected_version: number; target_role?: DraftRole | null }
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/balancer/draft/picks/${pickId}/select`, {
      method: "POST",
      body
    });
    return res.json();
  }

  static async autopick(
    pickId: number,
    body: { expected_version: number; reason?: "expiry" | "admin" }
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/balancer/draft/picks/${pickId}/autopick`, {
      method: "POST",
      body
    });
    return res.json();
  }

  static async override(
    pickId: number,
    body: {
      expected_version: number;
      player_id?: number | null;
      target_role?: DraftRole | null;
      note?: string | null;
    }
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/balancer/draft/picks/${pickId}/override`, {
      method: "POST",
      body
    });
    return res.json();
  }
}
