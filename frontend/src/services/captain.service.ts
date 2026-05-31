import { apiFetch } from "@/lib/api-fetch";
import { getTokenFromCookies } from "@/lib/auth-tokens";
import type { EncounterMapPoolEntry } from "@/types/tournament.types";
import type {
  ResultSubmissionInput,
  DisputeInput,
  VetoActionInput,
} from "@/types/admin.types";

export interface CaptainMatchReportInput {
  home_score: number;
  away_score: number;
  closeness: number; // 1..5 stars
}

class CaptainService {
  async buildMapVetoWebSocketUrl(encounterId: number): Promise<string> {
    const tournamentBase = process.env.NEXT_PUBLIC_TOURNAMENT_API_URL;
    const token = await getTokenFromCookies("aqt_access_token");

    if (tournamentBase) {
      const origin = typeof window !== "undefined" ? window.location.origin : "http://localhost";
      const url = new URL(tournamentBase, origin);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      url.pathname = `${url.pathname.replace(/\/$/, "")}/encounters/${encounterId}/map-pool/ws`;
      url.search = "";
      if (token) {
        url.searchParams.set("token", token);
      }
      return url.toString();
    }

    if (typeof window === "undefined") {
      const fallbackUrl = new URL(
        `/api/v1/encounters/${encounterId}/map-pool/ws`,
        "http://localhost",
      );
      if (token) {
        fallbackUrl.searchParams.set("token", token);
      }
      return fallbackUrl.pathname + fallbackUrl.search;
    }

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const url = new URL(
      `${protocol}//${window.location.host}/api/v1/encounters/${encounterId}/map-pool/ws`,
    );
    if (token) {
      url.searchParams.set("token", token);
    }
    return url.toString();
  }

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
