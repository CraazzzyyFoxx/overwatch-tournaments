import { apiFetch } from "@/lib/api-fetch";
import type {
  EncounterMapPoolEntry,
  EncounterMapPoolState,
} from "@/types/tournament.types";
import type {
  ResultSubmissionInput,
  DisputeInput,
  VetoActionInput,
} from "@/types/admin.types";

export interface CaptainMatchReportInput {
  home_score: number;
  away_score: number;
  closeness: number; // 1..10 score
}

class CaptainService {
  async submitResult(
    encounterId: number,
    data: ResultSubmissionInput
  ): Promise<{ id: number; result_status: string; home_score: number; away_score: number }> {
    const response = await apiFetch("tournament", `encounters/${encounterId}/submit-result`, {
      method: "POST",
      body: data,
    });
    return response.json();
  }

  async submitMatchReport(
    encounterId: number,
    data: CaptainMatchReportInput
  ): Promise<{
    id: number;
    result_status: string;
    home_score: number;
    away_score: number;
    closeness: number | null;
  }> {
    const response = await apiFetch(
      "tournament",
      `encounters/${encounterId}/submit-match-report`,
      { method: "POST", body: data }
    );
    return response.json();
  }

  async confirmResult(
    encounterId: number
  ): Promise<{ id: number; result_status: string; status: string }> {
    const response = await apiFetch("tournament", `encounters/${encounterId}/confirm-result`, {
      method: "POST",
    });
    return response.json();
  }

  async disputeResult(
    encounterId: number,
    data?: DisputeInput
  ): Promise<{ id: number; result_status: string }> {
    const response = await apiFetch("tournament", `encounters/${encounterId}/dispute-result`, {
      method: "POST",
      body: data ?? {},
    });
    return response.json();
  }

  async getMyRole(
    encounterId: number
  ): Promise<{ side: "home" | "away" | null }> {
    const response = await apiFetch("tournament", `encounters/${encounterId}/my-role`);
    return response.json();
  }

  async getMapPool(encounterId: number): Promise<EncounterMapPoolEntry[]> {
    const response = await apiFetch("tournament", `encounters/${encounterId}/map-pool`);
    return response.json();
  }

  /**
   * Fetch the full map-pool veto state. Returns `null` when the encounter has no
   * veto config / uninitialized pool (the backend answers 4xx), mirroring the old
   * WebSocket's "map_pool_unavailable" path so the UI can simply hide the panel.
   */
  async getMapPoolState(
    encounterId: number,
  ): Promise<EncounterMapPoolState | null> {
    const response = await apiFetch(
      "tournament",
      `encounters/${encounterId}/map-pool/state`,
      { throwOnError: false },
    );
    if (!response.ok) {
      return null;
    }
    return response.json();
  }

  async performVeto(
    encounterId: number,
    data: VetoActionInput
  ): Promise<{ id: number; map_id: number; status: string; picked_by: string | null }> {
    const response = await apiFetch("tournament", `encounters/${encounterId}/map-pool/veto`, {
      method: "POST",
      body: data,
    });
    return response.json();
  }
}

const captainService = new CaptainService();
export default captainService;
