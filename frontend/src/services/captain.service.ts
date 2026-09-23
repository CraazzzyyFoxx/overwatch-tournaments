import { apiFetch } from "@/lib/api/fetch";
import type { CaptainReport, CaptainReportsResponse } from "@/types/encounter.types";
interface CaptainMapCodeInput {
  map_index: number;
  code: string;
}

interface CaptainReportInput {
  home_score: number;
  away_score: number;
  /** 1..10, or null when the tournament disables/does not require match quality. */
  closeness: number | null;
  map_codes: CaptainMapCodeInput[];
  comment?: string | null;
  custom_fields?: Record<string, string>;
}

export interface CaptainReportSubmitResult {
  id: number;
  result_status: string;
  status: string;
  home_score: number;
  away_score: number;
  closeness: number | null;
  reports: CaptainReport[];
}

class CaptainService {
  async submitReport(
    encounterId: number,
    data: CaptainReportInput
  ): Promise<CaptainReportSubmitResult> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/report`, {
      method: "POST",
      body: data,
    });
    return response.json();
  }

  /**
   * Returns the reports *and* the tournament's report-form config: the config
   * rides this envelope so the dialog needs no second round trip and can never
   * render rules that disagree with the reports shown beside them.
   */
  async getReports(encounterId: number): Promise<CaptainReportsResponse> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/reports`);
    return response.json();
  }

  async getMyRole(
    encounterId: number
  ): Promise<{ side: "home" | "away" | null }> {
    const response = await apiFetch(`/api/v1/encounters/${encounterId}/my-role`);
    return response.json();
  }
}

const captainService = new CaptainService();
export default captainService;
