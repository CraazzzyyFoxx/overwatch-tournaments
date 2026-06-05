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
  AdminGoogleSheetMappingPreviewResponse,
  AdminGoogleSheetMappingSuggestInput,
  AdminGoogleSheetMappingSuggestResponse,
  ApplicationUserExportResponse,
  RegistrationUserExportResponse,
  BalanceExportResponse,
  BalanceSaveInput,
  BalancerApplication,
  BalancerPlayerCreateInput,
  BalancerPlayerExportResponse,
  BalancerPlayerImportPreviewResponse,
  BalancerPlayerImportResult,
  BalancerPlayerRecord,
  BalancerPlayerRoleSyncResponse,
  BalancerTournamentConfig,
  BalancerTournamentConfigUpsertInput,
  BalancerPlayerUpdateInput,
  RegistrationRankAutofillRequest,
  RegistrationRankAutofillResponse,
  DuplicateResolution,
  DuplicateStrategy,
  SavedBalance,
  StatusScope
} from "@/types/balancer-admin.types";

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

  static async listApplications(
    tournamentId: number,
    includeInactive = false
  ): Promise<BalancerApplication[]> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/applications`,
      {
        query: { include_inactive: includeInactive }
      }
    );
    return response.json();
  }

  static async createPlayersFromApplications(
    tournamentId: number,
    data: BalancerPlayerCreateInput
  ): Promise<BalancerPlayerRecord[]> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/players`,
      {
        method: "POST",
        body: data
      }
    );
    return response.json();
  }

  static async listPlayers(
    tournamentId: number,
    inPoolOnly = false
  ): Promise<BalancerPlayerRecord[]> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/players`,
      {
        query: { in_pool_only: inPoolOnly }
      }
    );
    return response.json();
  }

  static async updatePlayer(
    playerId: number,
    data: BalancerPlayerUpdateInput
  ): Promise<BalancerPlayerRecord> {
    const response = await apiFetch("balancer", `balancer/players/${playerId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  static async deletePlayer(playerId: number): Promise<void> {
    await apiFetch("balancer", `balancer/players/${playerId}`, {
      method: "DELETE"
    });
  }

  static async previewPlayerImport(
    tournamentId: number,
    file: File,
    matchApplicationRoles = false
  ): Promise<BalancerPlayerImportPreviewResponse> {
    const formData = new FormData();
    formData.append("data", file);
    formData.append("match_application_roles", String(matchApplicationRoles));

    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/players/import/preview`,
      {
        method: "POST",
        body: formData
      }
    );
    return response.json();
  }

  static async importPlayers(
    tournamentId: number,
    file: File,
    duplicateStrategy: DuplicateStrategy,
    matchApplicationRoles = false,
    resolutions?: Record<string, DuplicateResolution>
  ): Promise<BalancerPlayerImportResult> {
    const formData = new FormData();
    formData.append("data", file);
    formData.append("duplicate_strategy", duplicateStrategy);
    formData.append("match_application_roles", String(matchApplicationRoles));
    if (resolutions && Object.keys(resolutions).length > 0) {
      formData.append("resolutions_json", JSON.stringify(resolutions));
    }

    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/players/import`,
      {
        method: "POST",
        body: formData
      }
    );
    return response.json();
  }

  static async exportPlayers(tournamentId: number): Promise<BalancerPlayerExportResponse> {
    const response = await apiFetch(
      "tournament",
      `admin/balancer/tournaments/${tournamentId}/players/export`
    );
    return response.json();
  }

  static async syncPlayerRolesFromApplications(
    tournamentId: number
  ): Promise<BalancerPlayerRoleSyncResponse> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/players/application-roles`,
      {
        method: "POST",
        body: {}
      }
    );
    return response.json();
  }

  static async getTournamentConfig(tournamentId: number): Promise<BalancerTournamentConfig | null> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/config`
    );
    return response.json();
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

  static async getBalance(tournamentId: number): Promise<SavedBalance | null> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/balance`
    );
    return response.json();
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

  static async exportApplicationsToUsers(
    tournamentId: number
  ): Promise<ApplicationUserExportResponse> {
    const response = await apiFetch(
      "balancer",
      `balancer/tournaments/${tournamentId}/applications/export-users`,
      {
        method: "POST",
        body: {}
      }
    );
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
