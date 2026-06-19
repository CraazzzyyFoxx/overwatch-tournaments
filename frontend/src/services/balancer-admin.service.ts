import { apiFetch } from "@/lib/api-fetch";
import type { BalancerStatus } from "@/types/balancer-admin.types";
import {
  AdminRegistration,
  AdminRegistrationCreateInput,
  BalancerCustomStatus,
  BalancerCustomStatusCreateInput,
  BalancerCustomStatusUpdateInput,
  AdminRegistrationExclusionInput,
  AdminRegistrationForm,
  AdminRegistrationFormUpsert,
  AdminRegistrationUpdateInput,
  AdminGoogleSheetFeed,
  AdminGoogleSheetFeedSyncResponse,
  AdminGoogleSheetFeedUpsertInput,
  AdminGoogleSheetMappingPreviewInput,
  AdminGoogleSheetMappingPreviewInputV2,
  AdminGoogleSheetMappingPreviewResponse,
  AdminGoogleSheetMappingSuggestInput,
  AdminGoogleSheetMappingSuggestResponse,
  AdminGoogleSheetMappingValidationError,
  MappingCatalog,
  MappingPreviewResponseV2,
  RegistrationUserExportResponse,
  BalanceExportResponse,
  BalanceSaveInput,
  BalancerPlayerExportResponse,
  BalancerRegistrationRankHistoryEntry,
  BalancerTournamentConfig,
  BalancerTournamentConfigUpsertInput,
  RegistrationRankAutofillRequest,
  RegistrationRankAutofillResponse,
  SavedBalance,
  StatusScope,
  WorkspaceBalancerConfig,
  WorkspaceBalancerConfigUpsert
} from "@/types/balancer-admin.types";

// Endpoints whose response model is `X | None` return HTTP 200 with a `null`
// body from FastAPI, but the Go gateway omits the body for null data. Parse
// defensively so an empty body reads as `null` instead of throwing on `.json()`.
async function readJsonOrNull<T>(response: Response): Promise<T | null> {
  const text = await response.text();
  return text ? (JSON.parse(text) as T) : null;
}

export default class balancerAdminService {
  static async getTournamentSheet(tournamentId: number): Promise<AdminGoogleSheetFeed | null> {
    const response = await apiFetch("tournament", `admin/balancer/tournaments/${tournamentId}/sheet`);
    return response.json();
  }

  static async upsertTournamentSheet(
    tournamentId: number,
    data: AdminGoogleSheetFeedUpsertInput
  ): Promise<AdminGoogleSheetFeed> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/sheet`,
      {
        method: "PUT",
        body: data
      }
    );
    return response.json();
  }

  static async syncTournamentSheet(
    tournamentId: number
  ): Promise<AdminGoogleSheetFeedSyncResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/sheet/sync`,
      {
        method: "POST",
        body: {}
      }
    );
    return response.json();
  }

  static async suggestTournamentSheetMapping(
    tournamentId: number,
    data: AdminGoogleSheetMappingSuggestInput = {}
  ): Promise<AdminGoogleSheetMappingSuggestResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/sheet/suggest-mapping`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  static async previewTournamentSheetMapping(
    tournamentId: number,
    data: AdminGoogleSheetMappingPreviewInput
  ): Promise<AdminGoogleSheetMappingPreviewResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/sheet/preview`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  /**
   * Multi-row preview (v2). Returns a per-row breakdown with parsed fields,
   * field-level errors/warnings, and create/update/skip dispositions.
   */
  static async previewTournamentSheetMappingRows(
    tournamentId: number,
    data: AdminGoogleSheetMappingPreviewInputV2
  ): Promise<MappingPreviewResponseV2> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/sheet/preview`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  /**
   * Catalog that drives the visual mapper: available targets, parsers, value
   * categories, custom fields, and (optionally) the deduped header keys.
   */
  static async getTournamentSheetMappingCatalog(
    tournamentId: number,
    includeHeaders = true
  ): Promise<MappingCatalog> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/sheet/mapping-catalog`,
      {
        query: { include_headers: includeHeaders }
      }
    );
    return response.json();
  }

  /**
   * Upsert the feed, surfacing the structured HTTP 422 mapping-validation body
   * instead of throwing. Callers map `errors` onto per-target inline messages.
   */
  static async upsertTournamentSheetWithValidation(
    tournamentId: number,
    data: AdminGoogleSheetFeedUpsertInput
  ): Promise<
    | { ok: true; feed: AdminGoogleSheetFeed }
    | { ok: false; status: number; error: AdminGoogleSheetMappingValidationError }
  > {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/sheet`,
      {
        method: "PUT",
        body: data,
        throwOnError: false
      }
    );

    if (response.ok) {
      return { ok: true, feed: (await response.json()) as AdminGoogleSheetFeed };
    }
    if (response.status !== 422) {
      throw new Error(`Failed to save Google Sheets feed (${response.status}).`);
    }

    let error: AdminGoogleSheetMappingValidationError = {
      message: "Mapping validation failed.",
      errors: []
    };
    try {
      // FastAPI wraps a custom `HTTPException(detail=...)` as `{ detail: ... }`.
      // Our mapping validator passes `detail = { message, errors }`, so the
      // structured payload lives under `detail`. Fall back to legacy shapes.
      const body = (await response.json()) as {
        detail?: unknown;
        message?: unknown;
        errors?: unknown;
      };
      const detail = body.detail;
      const source =
        detail && typeof detail === "object" && !Array.isArray(detail)
          ? (detail as { message?: unknown; errors?: unknown })
          : body;
      error = {
        message:
          typeof source.message === "string"
            ? source.message
            : typeof detail === "string"
              ? detail
              : "Mapping validation failed.",
        errors: Array.isArray(source.errors)
          ? (source.errors as AdminGoogleSheetMappingValidationError["errors"])
          : []
      };
    } catch {
      error = { message: "Mapping validation failed.", errors: [] };
    }

    return { ok: false, status: response.status, error };
  }

  static async exportPlayers(tournamentId: number): Promise<BalancerPlayerExportResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/players/export`
    );
    return response.json();
  }

  static async getTournamentConfig(tournamentId: number): Promise<BalancerTournamentConfig | null> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/config`
    );
    return readJsonOrNull<BalancerTournamentConfig>(response);
  }

  static async upsertTournamentConfig(
    tournamentId: number,
    data: BalancerTournamentConfigUpsertInput
  ): Promise<BalancerTournamentConfig> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/config`,
      {
        method: "PUT",
        body: data
      }
    );
    return response.json();
  }

  static async getWorkspaceBalancerConfig(workspaceId: number): Promise<WorkspaceBalancerConfig> {
    const response = await apiFetch(
      "balancer",
      `balancer/workspaces/${workspaceId}/config`
    );
    return response.json();
  }

  static async upsertWorkspaceBalancerConfig(
    workspaceId: number,
    data: WorkspaceBalancerConfigUpsert
  ): Promise<WorkspaceBalancerConfig> {
    const response = await apiFetch(
      "balancer",
      `balancer/workspaces/${workspaceId}/config`,
      {
        method: "PUT",
        body: data
      }
    );
    return response.json();
  }

  static async getBalance(tournamentId: number): Promise<SavedBalance | null> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/balance`
    );
    return readJsonOrNull<SavedBalance>(response);
  }

  static async saveBalance(tournamentId: number, data: BalanceSaveInput): Promise<SavedBalance> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/balance`,
      {
        method: "PUT",
        body: data
      }
    );
    return response.json();
  }

  static async exportBalance(balanceId: number): Promise<BalanceExportResponse> {
    const response = await apiFetch("balancer", `balancer/balances/${balanceId}/export`, {
      method: "POST",
      body: {}
    });
    return response.json();
  }

  static async exportRegistrationsToUsers(
    tournamentId: number
  ): Promise<RegistrationUserExportResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registrations/export-users`,
      {
        method: "POST",
        body: {}
      }
    );
    return response.json();
  }

  static async importTeamsFromJson(
    tournamentId: number,
    file: File,
    payloadFormat: "auto" | "atravkovs" | "internal" = "auto"
  ): Promise<{ imported_teams: number }> {
    const formData = new FormData();
    formData.append("data", file);
    formData.append("payload_format", payloadFormat);
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/teams/import`,
      {
        method: "POST",
        body: formData
      }
    );
    return response.json();
  }

  // -----------------------------------------------------------------------
  // Registration management
  // -----------------------------------------------------------------------

  static async getRegistrationForm(tournamentId: number): Promise<AdminRegistrationForm | null> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registration-form`
    );
    return response.json();
  }

  static async upsertRegistrationForm(
    tournamentId: number,
    data: AdminRegistrationFormUpsert
  ): Promise<AdminRegistrationForm> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registration-form`,
      {
        method: "PUT",
        body: data
      }
    );
    return response.json();
  }

  static async listRegistrations(
    tournamentId: number,
    filters?: {
      status_filter?: string;
      inclusion_filter?: string;
      source_filter?: string;
      include_deleted?: boolean;
    }
  ): Promise<AdminRegistration[]> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registrations`,
      {
        query: filters
      }
    );
    return response.json();
  }

  static async createManualRegistration(
    tournamentId: number,
    data: AdminRegistrationCreateInput
  ): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registrations`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  static async updateRegistration(
    registrationId: number,
    data: AdminRegistrationUpdateInput
  ): Promise<AdminRegistration> {
    const response = await apiFetch("tournament", `admin/balancer/registrations/${registrationId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  static async approveRegistration(registrationId: number): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/registrations/${registrationId}/approve`,
      {
        method: "PATCH"
      }
    );
    return response.json();
  }

  static async rejectRegistration(registrationId: number): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/registrations/${registrationId}/reject`,
      {
        method: "PATCH"
      }
    );
    return response.json();
  }

  static async setRegistrationExclusion(
    registrationId: number,
    data: AdminRegistrationExclusionInput
  ): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/registrations/${registrationId}/exclusion`,
      {
        method: "PATCH",
        body: data
      }
    );
    return response.json();
  }

  static async withdrawRegistration(registrationId: number): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/registrations/${registrationId}/withdraw`,
      {
        method: "PATCH"
      }
    );
    return response.json();
  }

  static async restoreRegistration(registrationId: number): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/registrations/${registrationId}/restore`,
      {
        method: "PATCH"
      }
    );
    return response.json();
  }

  static async deleteRegistration(registrationId: number): Promise<void> {
    await apiFetch("tournament", `admin/balancer/registrations/${registrationId}`, {
      method: "DELETE"
    });
  }

  static async bulkApproveRegistrations(
    tournamentId: number,
    registrationIds: number[]
  ): Promise<{ approved: number; skipped: number }> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registrations/bulk-approve`,
      {
        method: "POST",
        body: { registration_ids: registrationIds }
      }
    );
    return response.json();
  }

  // -- Balancer status management ------------------------------------------

  static async setBalancerStatus(
    registrationId: number,
    balancerStatus: BalancerStatus
  ): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/registrations/${registrationId}/balancer-status`,
      {
        method: "PATCH",
        body: { balancer_status: balancerStatus }
      }
    );
    return response.json();
  }

  static async bulkAddToBalancer(
    tournamentId: number,
    registrationIds: number[],
    balancerStatus: BalancerStatus = "ready"
  ): Promise<{ updated: number; skipped: number }> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registrations/bulk-add-to-balancer`,
      {
        method: "POST",
        body: { registration_ids: registrationIds, balancer_status: balancerStatus }
      }
    );
    return response.json();
  }

  static async previewRegistrationRankAutofill(
    tournamentId: number,
    data: RegistrationRankAutofillRequest = {}
  ): Promise<RegistrationRankAutofillResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registrations/rank-autofill/preview`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  static async applyRegistrationRankAutofill(
    tournamentId: number,
    data: RegistrationRankAutofillRequest = {}
  ): Promise<RegistrationRankAutofillResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/registrations/rank-autofill/apply`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  static async getUserBalancerRankHistory(
    userId: number,
    workspaceId: number
  ): Promise<BalancerRegistrationRankHistoryEntry[]> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/users/${userId}/registration-rank-history`,
      {
        query: { workspace_id: workspaceId }
      }
    );
    const data = await response.json();
    return data.entries ?? [];
  }

  // -- Check-in management -------------------------------------------------

  static async checkInRegistration(
    registrationId: number,
    checkedIn: boolean
  ): Promise<AdminRegistration> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/registrations/${registrationId}/check-in`,
      {
        method: "PATCH",
        body: { checked_in: checkedIn }
      }
    );
    return response.json();
  }

  static async listCustomStatuses(workspaceId: number): Promise<BalancerCustomStatus[]> {
    const response = await apiFetch("tournament", `admin/ws/${workspaceId}/balancer-statuses`);
    return response.json();
  }

  static async listStatusCatalog(workspaceId: number): Promise<BalancerCustomStatus[]> {
    const response = await apiFetch(
      "tournament",
      `admin/ws/${workspaceId}/balancer-statuses/catalog`
    );
    return response.json();
  }

  static async createCustomStatus(
    workspaceId: number,
    data: BalancerCustomStatusCreateInput
  ): Promise<BalancerCustomStatus> {
    const response = await apiFetch(
      "tournament",
      `admin/ws/${workspaceId}/balancer-statuses/custom`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  static async updateCustomStatus(
    workspaceId: number,
    statusId: number,
    data: BalancerCustomStatusUpdateInput
  ): Promise<BalancerCustomStatus> {
    const response = await apiFetch(
      "tournament",
      `admin/ws/${workspaceId}/balancer-statuses/custom/${statusId}`,
      {
        method: "PATCH",
        body: data
      }
    );
    return response.json();
  }

  static async deleteCustomStatus(workspaceId: number, statusId: number): Promise<void> {
    await apiFetch("tournament", `admin/ws/${workspaceId}/balancer-statuses/custom/${statusId}`, {
      method: "DELETE"
    });
  }

  static async upsertBuiltinStatusOverride(
    workspaceId: number,
    scope: StatusScope,
    slug: string,
    data: BalancerCustomStatusUpdateInput
  ): Promise<BalancerCustomStatus> {
    const response = await apiFetch(
      "tournament",
      `admin/ws/${workspaceId}/balancer-statuses/system/${scope}/${slug}`,
      {
        method: "PUT",
        body: data
      }
    );
    return response.json();
  }

  static async resetBuiltinStatusOverride(
    workspaceId: number,
    scope: StatusScope,
    slug: string
  ): Promise<void> {
    await apiFetch(
      "tournament",
      `admin/ws/${workspaceId}/balancer-statuses/system/${scope}/${slug}`,
      {
        method: "DELETE"
      }
    );
  }
}
