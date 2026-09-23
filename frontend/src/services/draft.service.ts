import { apiFetch } from "@/lib/api/fetch";
import type {
  DraftBoard,
  DraftFeasibility,
  DraftJournalResponse,
  DraftPickExtendRequest,
  DraftPickOptionsResponse,
  DraftRole,
  DraftRoleEditRequest,
  DraftRoleEditResponse,
  DraftSeedRequest,
  DraftSeedResponse,
  DraftSession,
  DraftSessionCreateRequest,
  DraftTeamFitResponse,
  DraftTeamQueueResponse
} from "@/types/draft.types";
import type { RanksExportResponse } from "@/types/balancer-admin.types";

export const draftEndpoints = {
  feasibility: (sessionId: number) => `/api/v1/balancer/draft/sessions/${sessionId}/feasibility`,
  pickOptions: (pickId: number) => `/api/v1/balancer/draft/picks/${pickId}/options`,
  playerRole: (sessionId: number, playerId: number) =>
    `/api/v1/balancer/draft/sessions/${sessionId}/players/${playerId}/roles`
};

// All draft endpoints live on balancer-service under /api/v1/balancer/draft/...
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
    const res = await apiFetch(`/api/v1/balancer/draft/tournaments/${tournamentId}/draft`);
    return readJsonOrNull<DraftBoard>(res);
  }

  static async getSessionBoard(sessionId: number): Promise<DraftBoard> {
    const res = await apiFetch(`/api/v1/balancer/draft/sessions/${sessionId}/board`);
    return res.json();
  }

  static async getSession(sessionId: number): Promise<DraftSession> {
    const res = await apiFetch(`/api/v1/balancer/draft/sessions/${sessionId}`);
    return res.json();
  }

  /** The server's 1..99 fit of every seatable player for one team. */
  static async getTeamFit(sessionId: number, teamId: number): Promise<DraftTeamFitResponse> {
    const res = await apiFetch(`/api/v1/balancer/draft/sessions/${sessionId}/teams/${teamId}/fit`);
    return res.json();
  }

  /** A captain's private pick queue ("My list") plus the autopick preview while on the clock. */
  static async getTeamQueue(sessionId: number, teamId: number): Promise<DraftTeamQueueResponse> {
    const res = await apiFetch(`/api/v1/balancer/draft/sessions/${sessionId}/teams/${teamId}/queue`);
    return res.json();
  }

  /** Replace the whole queue; order is the autopick priority. */
  static async setTeamQueue(
    sessionId: number,
    teamId: number,
    playerIds: number[]
  ): Promise<DraftTeamQueueResponse> {
    const res = await apiFetch(`/api/v1/balancer/draft/sessions/${sessionId}/teams/${teamId}/queue`, {
      method: "PUT",
      body: { player_ids: playerIds }
    });
    return res.json();
  }

  /** Organizer journal, newest first. */
  static async getJournal(sessionId: number, limit = 100): Promise<DraftJournalResponse> {
    const res = await apiFetch(`/api/v1/balancer/draft/sessions/${sessionId}/journal`, {
      query: { limit }
    });
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
    const res = await apiFetch(`/api/v1/balancer/draft/tournaments/${tournamentId}/sessions`, {
      method: "POST",
      body
    });
    return res.json();
  }

  /** Every session ever created for the tournament, newest first. */
  static async listSessions(tournamentId: number): Promise<DraftSession[]> {
    const res = await apiFetch(`/api/v1/balancer/draft/tournaments/${tournamentId}/sessions`);
    return res.json();
  }

  /**
   * Erase a session with its teams, pool, picks and audit trail. Answers 204,
   * so there is no body to parse. Rejected with 409 while the draft is live or
   * paused — cancel it first.
   */
  static async deleteSession(tournamentId: number, sessionId: number): Promise<void> {
    await apiFetch(`/api/v1/balancer/draft/tournaments/${tournamentId}/sessions/${sessionId}`, {
      method: "DELETE"
    });
  }

  static async seed(
    tournamentId: number,
    sessionId: number,
    body: DraftSeedRequest
  ): Promise<DraftSeedResponse> {
    const res = await apiFetch(`/api/v1/balancer/draft/tournaments/${tournamentId}/sessions/${sessionId}/seed`,
      { method: "POST", body }
    );
    return res.json();
  }

  static async lifecycle(
    tournamentId: number,
    sessionId: number,
    action: "start" | "pause" | "resume" | "cancel" | "export" | "rollback"
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/v1/balancer/draft/tournaments/${tournamentId}/sessions/${sessionId}/${action}`,
      { method: "POST" }
    );
    return res.json();
  }

  /** Refresh the ranks of players this draft already exported; teams stay as they are. */
  static async exportRanks(
    tournamentId: number,
    sessionId: number
  ): Promise<RanksExportResponse> {
    const res = await apiFetch(`/api/v1/balancer/draft/tournaments/${tournamentId}/sessions/${sessionId}/export-ranks`,
      { method: "POST" }
    );
    return res.json();
  }

  // --- pick actions (keyed by pick_id) ---
  static async select(
    pickId: number,
    body: { player_id: number; expected_version: number; target_role?: DraftRole | null }
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/v1/balancer/draft/picks/${pickId}/select`, {
      method: "POST",
      body
    });
    return res.json();
  }

  static async autopick(
    pickId: number,
    body: { expected_version: number; reason?: "expiry" | "admin" }
  ): Promise<DraftSession> {
    const res = await apiFetch(`/api/v1/balancer/draft/picks/${pickId}/autopick`, {
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
    const res = await apiFetch(`/api/v1/balancer/draft/picks/${pickId}/override`, {
      method: "POST",
      body
    });
    return res.json();
  }

  /** Admin: add seconds to the current pick's clock. */
  static async extend(pickId: number, body: DraftPickExtendRequest): Promise<DraftSession> {
    const res = await apiFetch(`/api/v1/balancer/draft/picks/${pickId}/extend`, {
      method: "POST",
      body
    });
    return res.json();
  }
}
