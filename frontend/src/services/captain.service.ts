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
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/submit-result`, {
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
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/submit-match-report`,
      { method: "POST", body: data }
    );
    return response.json();
  }

  async confirmResult(
    encounterId: number
  ): Promise<{ id: number; result_status: string; status: string }> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/confirm-result`, {
      method: "POST",
    });
    return response.json();
  }

  async disputeResult(
    encounterId: number,
    data?: DisputeInput
  ): Promise<{ id: number; result_status: string }> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/dispute-result`, {
      method: "POST",
      body: data ?? {},
    });
    return response.json();
  }

  async getMyRole(
    encounterId: number
  ): Promise<{ side: "home" | "away" | null }> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/my-role`);
    return response.json();
  }

  async getMapPool(encounterId: number): Promise<EncounterMapPoolEntry[]> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/map-pool`);
    return response.json();
  }

  /**
   * Fetch the full map-pool veto state. The backend now answers 200 with
   * `session: null` + `reason` ("not_configured" | "teams_unknown") when the
   * room can't exist yet; reads also lazily create the session when the
   * encounter is ready. `null` is kept only for hard failures (404 encounter).
   */
  async getMapPoolState(
    encounterId: number,
  ): Promise<EncounterMapPoolState | null> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/map-pool/state`,
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
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/map-pool/veto`, {
      method: "POST",
      body: data,
    });
    return response.json();
  }
}

const captainService = new CaptainService();
export default captainService;
