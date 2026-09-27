import { apiFetch } from "@/lib/api/fetch";
import type { FfaGameResultsInput, FfaLobby } from "@/types/ffa.types";

/**
 * The FFA lobby reads and the three organizer writes.
 *
 * A game is addressed by its POSITION, never by a game id: a lobby may replay
 * a cancelled position, and only the position tells the two plays apart
 * (gateway `admin_misc_routes.go`).
 *
 * The stage read answers every lobby of the stage and the encounter read
 * answers one — the same `FfaLobby` either way, so the table renders from one
 * model on both screens.
 */
const ffaService = {
  async getStage(tournamentId: number, stageId: number): Promise<FfaLobby[]> {
    const response = await apiFetch(
      `/api/v1/tournaments/${tournamentId}/stages/${stageId}/ffa`,
    );
    return response.json();
  },

  /**
   * The organizer's read of the same lobbies.
   *
   * Identical shape, one difference that matters: the public route runs its
   * answer through `public_view` and strips the columns marked `public: false`
   * together with every value under them, in `rules`, in the row totals and in
   * the game cells. The entry dialog has to show exactly those columns, so the
   * organizer's screens read this route instead (spec §7.3).
   */
  async getStageAdmin(tournamentId: number, stageId: number): Promise<FfaLobby[]> {
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/stages/${stageId}/ffa`,
    );
    return response.json();
  },

  async getLobby(encounterId: number): Promise<FfaLobby> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/ffa`);
    return response.json();
  },

  async setGameResults(
    encounterId: number,
    position: number,
    input: FfaGameResultsInput,
  ): Promise<FfaLobby> {
    const response = await apiFetch(
      `/api/v1/admin/encounters/${encounterId}/ffa/games/${position}/results`,
      { method: "POST", body: input },
    );
    return response.json();
  },

  /** Voids a played position; the reason is mandatory and lands in the audit. */
  async cancelGame(encounterId: number, position: number, reason: string): Promise<FfaLobby> {
    const response = await apiFetch(
      `/api/v1/admin/encounters/${encounterId}/ffa/games/${position}/cancel`,
      { method: "POST", body: { reason } },
    );
    return response.json();
  },

  /** Resizes the lobby's series. The server refuses to cut below games played. */
  async setGamesCount(encounterId: number, games: number): Promise<FfaLobby> {
    const response = await apiFetch(
      `/api/v1/admin/encounters/${encounterId}/ffa/games-count`,
      { method: "POST", body: { games } },
    );
    return response.json();
  },
};

export default ffaService;
