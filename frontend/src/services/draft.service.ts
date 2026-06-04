import { apiFetch } from "@/lib/api-fetch";
import type {
  DraftBoard,
  DraftRole,
  DraftSeedRequest,
  DraftSession,
  DraftSessionCreateRequest,
  DraftSuggestionsResponse
} from "@/types/draft.types";

// All draft endpoints live on balancer-service under /api/balancer/draft/...
// Reads are public (spectating); writes use apiFetch's automatic bearer token.
export default class draftService {
  static async getTournamentBoard(tournamentId: number): Promise<DraftBoard | null> {
    const res = await apiFetch("balancer", `draft/tournaments/${tournamentId}/draft`);
    return res.json();
  }

  static async getSessionBoard(sessionId: number): Promise<DraftBoard> {
    const res = await apiFetch("balancer", `draft/sessions/${sessionId}/board`);
    return res.json();
  }

  static async getSession(sessionId: number): Promise<DraftSession> {
    const res = await apiFetch("balancer", `draft/sessions/${sessionId}`);
    return res.json();
  }

  static async getSuggestions(sessionId: number): Promise<DraftSuggestionsResponse> {
    const res = await apiFetch("balancer", `draft/sessions/${sessionId}/suggestions`);
    return res.json();
  }

  // --- admin lifecycle (keyed by tournament_id) ---
  static async createSession(
    tournamentId: number,
    body: DraftSessionCreateRequest
  ): Promise<DraftSession> {
    const res = await apiFetch("balancer", `draft/tournaments/${tournamentId}/sessions`, {
      method: "POST",
      body: JSON.stringify(body)
    });
    return res.json();
  }

  static async seed(
    tournamentId: number,
    sessionId: number,
    body: DraftSeedRequest
  ): Promise<DraftSession> {
    const res = await apiFetch(
      "balancer",
      `draft/tournaments/${tournamentId}/sessions/${sessionId}/seed`,
      { method: "POST", body: JSON.stringify(body) }
    );
    return res.json();
  }

  static async lifecycle(
    tournamentId: number,
    sessionId: number,
    action: "start" | "pause" | "resume" | "cancel" | "export"
  ): Promise<DraftSession> {
    const res = await apiFetch(
      "balancer",
      `draft/tournaments/${tournamentId}/sessions/${sessionId}/${action}`,
      { method: "POST" }
    );
    return res.json();
  }

  // --- pick actions (keyed by pick_id) ---
  static async select(
    pickId: number,
    body: { player_id: number; expected_version: number; target_role?: DraftRole | null }
  ): Promise<DraftSession> {
    const res = await apiFetch("balancer", `draft/picks/${pickId}/select`, {
      method: "POST",
      body: JSON.stringify(body)
    });
    return res.json();
  }

  static async autopick(
    pickId: number,
    body: { expected_version: number; reason?: "expiry" | "admin" }
  ): Promise<DraftSession> {
    const res = await apiFetch("balancer", `draft/picks/${pickId}/autopick`, {
      method: "POST",
      body: JSON.stringify(body)
    });
    return res.json();
  }

  static async override(
    pickId: number,
    body: { expected_version: number; player_id?: number | null; note?: string | null }
  ): Promise<DraftSession> {
    const res = await apiFetch("balancer", `draft/picks/${pickId}/override`, {
      method: "POST",
      body: JSON.stringify(body)
    });
    return res.json();
  }
}
