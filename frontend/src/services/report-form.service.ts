import { apiFetch } from "@/lib/api/fetch";
import type { MatchReportForm } from "@/types/encounter.types";

type MatchReportFormUpsert = Omit<MatchReportForm, "tournament_id">;

class ReportFormService {
  async getReportForm(tournamentId: number): Promise<MatchReportForm> {
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/report-form`
    );
    return response.json();
  }

  async saveReportForm(
    tournamentId: number,
    body: MatchReportFormUpsert
  ): Promise<MatchReportForm> {
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/report-form`,
      {
        method: "PUT",
        body,
      }
    );
    return response.json();
  }
}

const reportFormService = new ReportFormService();
export default reportFormService;
