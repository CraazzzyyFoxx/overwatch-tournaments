import { apiFetch } from "@/lib/api-fetch";
import type {
  PickBanConfig,
  PickBanConfigUpsertInput,
  PickBanEntry,
  PickBanGame,
  PickBanKind,
  PickBanState,
  PickBanUndo
} from "@/types/tournament.types";

export interface PickBanActionInput {
  item_id: number;
  action: "ban" | "pick" | "protect";
}

interface ElectOpenerInput {
  first_side: "home" | "away";
}

interface GameReportInput {
  home_score: number;
  away_score: number;
}

interface GameReportResult {
  disputed: boolean;
  resolved: boolean;
  game: PickBanGame;
}

interface ReadinessMap {
  home: boolean;
  away: boolean;
}

class PickBanService {
  /**
   * Fetch one kind's pick-ban room state. 200-with-`reason` contract: `null`
   * is reserved for hard failures (404 encounter), never for "not configured
   * yet" / "not ready yet" — those come back as `reason` on a normal 200.
   */
  async getPickBanState(kind: PickBanKind, encounterId: number): Promise<PickBanState | null> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/pick-ban/${kind}/state`, {
      throwOnError: false
    });
    if (!response.ok) return null;
    return response.json();
  }

  async performPickBanAction(
    kind: PickBanKind,
    encounterId: number,
    data: PickBanActionInput
  ): Promise<PickBanEntry> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/pick-ban/${kind}/act`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async electOpener(
    kind: PickBanKind,
    encounterId: number,
    data: ElectOpenerInput
  ): Promise<unknown> {
    const response = await apiFetch(
      `/api/v1/encounters/${encounterId}/pick-ban/${kind}/elect-opener`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  /**
   * Records the calling captain's consent to undo the session's last action.
   * The OPPONENT's matching call is what applies it — this is a two-sided
   * agreement, not a take-back. `consent: false` withdraws an open request
   * (the asker changing their mind and the opponent refusing are one outcome).
   */
  async undoLastAction(
    kind: PickBanKind,
    encounterId: number,
    consent = true
  ): Promise<PickBanUndo> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/pick-ban/${kind}/undo`, {
      method: "POST",
      body: { consent }
    });
    return response.json();
  }

  /**
   * Files the calling captain's claim for ONE game. Agreement confirms the
   * game (`resolved`) and opens the next position; a clash leaves both claims
   * standing (`disputed`). A confirmed game rejects this with 409
   * `result_locked` — only `correctGameResult` may change it.
   */
  async reportGame(
    encounterId: number,
    gameId: number,
    data: GameReportInput
  ): Promise<GameReportResult> {
    const response = await apiFetch(
      `/api/v1/encounters/${encounterId}/games/${gameId}/report`,
      { method: "POST", body: data }
    );
    return response.json();
  }

  /** Names the map a freeplay position was played on, before its result. */
  async selectGameMap(
    encounterId: number,
    gameId: number,
    data: { map_id: number }
  ): Promise<{ game: PickBanGame }> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/games/${gameId}/map`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /**
   * Admin correction of a confirmed or disputed game. `reason` is required —
   * it is what the result audit records. 409 `downstream_started` when a later
   * encounter of the bracket has already begun on the old result.
   */
  async correctGameResult(
    encounterId: number,
    gameId: number,
    data: { home_score: number; away_score: number; reason: string }
  ): Promise<{ game: PickBanGame; rebuilt_rounds: number[] }> {
    const response = await apiFetch(
      `/api/v1/admin/encounters/${encounterId}/games/${gameId}/result`,
      { method: "POST", body: data }
    );
    return response.json();
  }

  /** Confirms the calling captain's side is ready to begin the encounter's
   * pre-game phase (shared gate across both pick-ban kinds). */
  async markReady(encounterId: number): Promise<{ readiness: ReadinessMap }> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/ready`, { method: "POST" });
    return response.json();
  }

  async listPublicConfigs(tournamentId: number): Promise<{ configs: PickBanConfig[] }> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/pick-ban-configs`, {
      skipWorkspace: true,
    });
    return response.json();
  }

  async listConfigs(tournamentId: number): Promise<{ configs: PickBanConfig[] }> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/pick-ban-configs`);
    return response.json();
  }

  async upsertConfig(tournamentId: number, data: PickBanConfigUpsertInput): Promise<PickBanConfig> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/pick-ban-configs`, {
      method: "PUT",
      body: data
    });
    return response.json();
  }

  async deleteConfig(configId: number): Promise<{ deleted: boolean }> {
    const response = await apiFetch(`/api/v1/admin/pick-ban-configs/${configId}`, {
      method: "DELETE"
    });
    return response.json();
  }
}

const pickBanService = new PickBanService();
export default pickBanService;
