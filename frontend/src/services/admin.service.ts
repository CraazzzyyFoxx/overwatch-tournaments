import { apiFetch } from "@/lib/api-fetch";
import { PaginatedResponse } from "@/types/pagination.types";
import {
  Tournament,
  Standings,
  Stage,
  StageItem,
  StageItemInput,
  StageItemType,
  PickBanKind,
  PickBanState,
  TournamentImageSlot
} from "@/types/tournament.types";
import { Team, Player } from "@/types/team.types";
import { Encounter } from "@/types/encounter.types";
import { User } from "@/types/user.types";
import { Hero } from "@/types/hero.types";
import { Achievement } from "@/types/achievement.types";
import { Gamemode } from "@/types/gamemode.types";
import { MapRead } from "@/types/map.types";
import type {
  TournamentLink,
  TournamentLinkCreateInput,
  TournamentLinkUpdateInput
} from "@/types/stream.types";
import {
  TournamentCreateInput,
  TournamentUpdateInput,
  TournamentPreviewAccessEntry,
  TournamentStatusTransitionInput,
  TournamentReadiness,
  TournamentPhaseScheduleEntryInput,
  StageCreateInput,
  StageUpdateInput,
  StageItemCreateInput,
  StageItemInputCreateInput,
  StageItemInputUpdateInput,
  StageMergeGroupStagesInput,
  ChallongeSyncLogEntry,
  ChallongeTeamSyncPreview,
  ChallongeTeamSyncRequest,
  ChallongeTeamSyncResult,
  TeamCreateInput,
  TeamUpdateInput,
  PlayerCreateInput,
  PlayerUpdateInput,
  EncounterCreateInput,
  EncounterUpdateInput,
  MatchUpdateInput,
  StandingUpdateInput,
  UserCreateInput,
  UserUpdateInput,
  SocialAccountCreateInput,
  SocialAccountUpdateInput,
  SocialVisibilityInput,
  HeroCreateInput,
  HeroUpdateInput,
  GamemodeCreateInput,
  GamemodeUpdateInput,
  MapCreateInput,
  MapUpdateInput,
  CatalogAliasAttachInput,
  CatalogAliasMissQuery,
  CatalogAliasMissRead,
  AchievementCreateInput,
  AchievementUpdateInput,
  AchievementRegistryEntry,
  AchievementLibraryRule,
  AchievementLibraryWorkspace,
  AchievementRuleExportEnvelope,
  AchievementRuleImportResult,
  AchievementRule,
  AchievementRuleCreateInput,
  AchievementRuleUpdateInput,
  AchievementOverrideCreateInput,
  AchievementOverrideRead,
  ConditionTreeValidateResponse,
  ConditionTypeInfo,
  EvaluationRunRead,
  HardResetResultRead,
  BulkOperationResult,
  TournamentComputationJob,
  UserMergePreviewRequest,
  UserMergePreviewResponse,
  UserMergeExecuteRequest,
  UserMergeExecuteResponse,
  DiscordChannelRead,
  DiscordChannelInput,
  LogHistoryResponse,
  LogProcessingRecord,
  LogProcessingStats,
  LogProcessingStatus,
  LogUploadResponse,
  SeedResultRead,
  PlayerSubRole,
  PlayerSubRoleCreateInput,
  PlayerSubRoleUpdateInput,
  SettingRead,
  SettingUpsertInput,
  RankCollectionStatusRow,
  CollectTriggerInput,
  CollectTriggerResult,
  RankFetchLogRow,
  RankFetchLogQuery,
  RankCollectionStats,
  SubscriptionCollectionStats,
  SubscriptionCheckLogRow,
  SubscriptionCheckLogQuery,
  SubscriptionUserCollectionRow,
  SubscriptionCollectTriggerInput,
  SubscriptionCollectTriggerResult,
  StreamPollHealth,
  EncounterResultAuditRead,
  EncounterResultRead,
  EncounterSetResultInput,
  EncounterReportsQuery,
  EncounterReportsRow,
  EncounterReportsStats,
  AdminMatchDetail,
  AdminMatchRow,
  AdminMatchesQuery,
  AuditLogQuery,
  AuditLogRead,
  StageBracketPreviewMatch,
} from "@/types/admin.types";

/**
 * Serialise the reports filter set once — the list and its counters must send
 * an identical scope or the chips would count a different population than the
 * table shows.
 */
function buildEncounterReportsQuery(params: EncounterReportsQuery): string {
  const search = new URLSearchParams();
  search.set("workspace_id", String(params.workspace_id));
  if (params.page != null) search.set("page", String(params.page));
  if (params.per_page != null) search.set("per_page", String(params.per_page));
  if (params.query) search.set("query", params.query);
  if (params.tournament_id != null) search.set("tournament_id", String(params.tournament_id));
  if (params.stage_id != null) search.set("stage_id", String(params.stage_id));
  if (params.mismatch_only) search.set("mismatch_only", "true");
  if (params.reported_count != null) search.set("reported_count", String(params.reported_count));
  // Repeated, not comma-joined: the backend field is a list and the gateway
  // forwards every occurrence.
  for (const status of params.result_status ?? []) search.append("result_status", status);
  return search.toString();
}

/**
 * Serialise the parsed-matches filter set. `log_status` repeats rather than
 * comma-joining: the backend field is a list and the gateway forwards every
 * occurrence.
 */
function buildAdminMatchesQuery(params: AdminMatchesQuery): string {
  const search = new URLSearchParams();
  search.set("workspace_id", String(params.workspace_id));
  if (params.page != null) search.set("page", String(params.page));
  if (params.per_page != null) search.set("per_page", String(params.per_page));
  if (params.query) search.set("query", params.query);
  if (params.tournament_id != null) search.set("tournament_id", String(params.tournament_id));
  if (params.encounter_id != null) search.set("encounter_id", String(params.encounter_id));
  if (params.map_id != null) search.set("map_id", String(params.map_id));
  if (params.unlinked_only) search.set("unlinked_only", "true");
  for (const status of params.log_status ?? []) search.append("log_status", status);
  return search.toString();
}

/**
 * Serialise the common page/per_page/search/sort/order filter set shared by
 * the simple admin list endpoints (users, gamemodes, ...).
 */
function buildAdminListQuery(params: {
  page?: number;
  per_page?: number;
  search?: string;
  sort?: string;
  order?: string;
}): Record<string, unknown> {
  return {
    ...(params.page != null && { page: params.page }),
    ...(params.per_page != null && { per_page: params.per_page }),
    ...(params.search && { search: params.search }),
    ...(params.sort && { sort: params.sort }),
    ...(params.order && { order: params.order })
  };
}

class AdminService {
  private async getTournamentJob(jobId: number): Promise<TournamentComputationJob> {
    const response = await apiFetch(`/api/v1/admin/tournament-jobs/${jobId}`);
    return response.json();
  }

  private async waitForTournamentJob(
    initialJob: TournamentComputationJob,
    timeoutMs = 120_000
  ): Promise<TournamentComputationJob> {
    const deadline = Date.now() + timeoutMs;
    let job = initialJob;

    while (job.status === "pending" || job.status === "running") {
      if (Date.now() >= deadline) {
        throw new Error(`Tournament computation job ${job.id} timed out`);
      }
      await new Promise((resolve) => setTimeout(resolve, 750));
      job = await this.getTournamentJob(job.id);
    }

    if (job.status !== "succeeded") {
      const message = job.error || `Tournament computation job ${job.id} ${job.status}`;
      const error = new Error(message) as Error & {
        detail?: { code: string; message: string };
      };
      if (message.includes("upstream_stages_not_completed")) {
        error.detail = { code: "upstream_stages_not_completed", message };
      }
      throw error;
    }

    return job;
  }

  // ─── Tournament CRUD ───────────────────────────────────────────────────────

  async createTournament(data: TournamentCreateInput): Promise<Tournament> {
    const response = await apiFetch("/api/v1/admin/tournaments", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async getTournament(id: number): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}`);
    return response.json();
  }

  /** Readiness aggregate for the hub living checklist (D13, §7.1). */
  async getTournamentReadiness(id: number): Promise<TournamentReadiness> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}/readiness`);
    return response.json();
  }

  async updateTournament(id: number, data: TournamentUpdateInput): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async setTournamentSchedule(
    id: number,
    schedule: TournamentPhaseScheduleEntryInput[]
  ): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}/schedule`, {
      method: "PUT",
      body: { schedule }
    });
    return response.json();
  }

  async deleteTournament(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/tournaments/${id}`, {
      method: "DELETE"
    });
  }

  async createTournamentWithGroups(params: {
    workspace_id: number;
    challonge_slug: string;
    is_league: boolean;
    start_date: string;
    end_date: string;
    division_grid_version_id?: number | null;
  }): Promise<Tournament> {
    const response = await apiFetch("/api/v1/tournament/create/with_groups", {
      method: "POST",
      query: params
    });
    return response.json();
  }

  async toggleTournamentFinished(tournamentId: number): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/finish`, {
      method: "POST"
    });
    return response.json();
  }

  // ─── Tournament preview allowlist (hidden tournaments) ──────────────────────

  async getTournamentPreviewAccess(tournamentId: number): Promise<TournamentPreviewAccessEntry[]> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/preview-access`);
    return response.json();
  }

  async addTournamentPreviewUser(
    tournamentId: number,
    authUserId: number
  ): Promise<TournamentPreviewAccessEntry> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/preview-access`, {
      method: "POST",
      body: { auth_user_id: authUserId }
    });
    return response.json();
  }

  async removeTournamentPreviewUser(tournamentId: number, authUserId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/preview-access/${authUserId}`, {
      method: "DELETE"
    });
  }

  // ─── Tournament links (typed Discord/stream/VOD/... links) ─────────────────

  /**
   * Flat array, not a `PaginatedResponse`: a tournament carries a handful of
   * links and the backend returns them already ordered by `(sort_order, id)`.
   */
  async listTournamentLinks(
    tournamentId: number,
    opts?: { activeOnly?: boolean }
  ): Promise<TournamentLink[]> {
    const response = await apiFetch("/api/v1/admin/tournament-links", {
      query: {
        tournament_id: tournamentId,
        ...(opts?.activeOnly != null && { active_only: opts.activeOnly })
      }
    });
    return response.json();
  }

  async createTournamentLink(data: TournamentLinkCreateInput): Promise<TournamentLink> {
    const response = await apiFetch("/api/v1/admin/tournament-links", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateTournamentLink(
    linkId: number,
    data: TournamentLinkUpdateInput
  ): Promise<TournamentLink> {
    const response = await apiFetch(`/api/v1/admin/tournament-links/${linkId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  /** Soft delete — the row is flipped to `is_active: false`, not destroyed.
   *  Restoring is `updateTournamentLink(id, { is_active: true })`. */
  async deleteTournamentLink(linkId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/tournament-links/${linkId}`, {
      method: "DELETE"
    });
  }

  // ─── Team CRUD ─────────────────────────────────────────────────────────────

  async createTeam(data: TeamCreateInput): Promise<Team> {
    const response = await apiFetch("/api/v1/admin/teams", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async getTeam(id: number): Promise<Team> {
    const response = await apiFetch(`/api/v1/admin/teams/${id}`);
    return response.json();
  }

  async updateTeam(id: number, data: TeamUpdateInput): Promise<Team> {
    const response = await apiFetch(`/api/v1/admin/teams/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteTeam(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/teams/${id}`, {
      method: "DELETE"
    });
  }

  // ─── Team image ────────────────────────────────────────────────────────────

  async uploadTeamImage(teamId: number, file: File): Promise<Team> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiFetch(`/api/v1/admin/teams/${teamId}/image`, {
      method: "POST",
      body: formData
    });
    return response.json();
  }

  async deleteTeamImage(teamId: number): Promise<Team> {
    const response = await apiFetch(`/api/v1/admin/teams/${teamId}/image`, {
      method: "DELETE"
    });
    return response.json();
  }

  // ─── Tournament images ─────────────────────────────────────────────────────

  async uploadTournamentImage(
    tournamentId: number,
    slot: TournamentImageSlot,
    file: File
  ): Promise<Tournament> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/images/${slot}`,
      {
        method: "POST",
        body: formData
      }
    );
    return response.json();
  }

  async deleteTournamentImage(
    tournamentId: number,
    slot: TournamentImageSlot
  ): Promise<Tournament> {
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/images/${slot}`,
      {
        method: "DELETE"
      }
    );
    return response.json();
  }

  async addPlayerToTeam(teamId: number, data: PlayerCreateInput): Promise<Player> {
    const response = await apiFetch(`/api/v1/admin/teams/${teamId}/players`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async removePlayerFromTeam(teamId: number, playerId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/teams/${teamId}/players/${playerId}`, {
      method: "DELETE"
    });
  }

  async getChallongeTeamSyncPreview(tournamentId: number): Promise<ChallongeTeamSyncPreview> {
    const response = await apiFetch("/api/v1/teams/challonge/preview", {
      query: { tournament_id: tournamentId }
    });
    return response.json();
  }

  async syncTeamsFromChallonge(
    tournamentId: number,
    data: ChallongeTeamSyncRequest
  ): Promise<ChallongeTeamSyncResult> {
    const response = await apiFetch("/api/v1/teams/create/challonge", {
      method: "POST",
      query: { tournament_id: tournamentId },
      body: data
    });
    return response.json();
  }

  // ─── Player CRUD ───────────────────────────────────────────────────────────

  async createPlayer(data: PlayerCreateInput): Promise<Player> {
    const response = await apiFetch("/api/v1/admin/players", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updatePlayer(id: number, data: PlayerUpdateInput): Promise<Player> {
    const response = await apiFetch(`/api/v1/admin/players/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deletePlayer(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/players/${id}`, {
      method: "DELETE"
    });
  }

  async getPlayerSubRoles(params: {
    workspace_id: number;
    role?: string;
    include_inactive?: boolean;
  }): Promise<PlayerSubRole[]> {
    const response = await apiFetch("/api/v1/admin/player-sub-roles", {
      query: params
    });
    return response.json();
  }

  async createPlayerSubRole(data: PlayerSubRoleCreateInput): Promise<PlayerSubRole> {
    const response = await apiFetch("/api/v1/admin/player-sub-roles", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updatePlayerSubRole(id: number, data: PlayerSubRoleUpdateInput): Promise<PlayerSubRole> {
    const response = await apiFetch(`/api/v1/admin/player-sub-roles/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deletePlayerSubRole(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/player-sub-roles/${id}`, {
      method: "DELETE"
    });
  }

  // ─── Encounter CRUD ────────────────────────────────────────────────────────

  async createEncounter(data: EncounterCreateInput): Promise<Encounter> {
    const response = await apiFetch("/api/v1/admin/encounters", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateEncounter(id: number, data: EncounterUpdateInput): Promise<Encounter> {
    const response = await apiFetch(`/api/v1/admin/encounters/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteEncounter(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/encounters/${id}`, {
      method: "DELETE"
    });
  }

  /**
   * The single admin result write: score, status, result_status and the audit
   * row move together. An empty body confirms whatever is already there, which
   * covers the common case of two agreeing captain reports.
   */
  async setEncounterResult(
    id: number,
    data: EncounterSetResultInput = {}
  ): Promise<EncounterResultRead> {
    const response = await apiFetch(`/api/v1/admin/encounters/${id}/result`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** Un-confirm a result so it can be replayed or re-reported. */
  async reopenEncounterResult(id: number): Promise<EncounterResultRead> {
    const response = await apiFetch(`/api/v1/admin/encounters/${id}/result/reopen`, {
      method: "POST"
    });
    return response.json();
  }

  /** Every recorded transition of this encounter's result, newest first. */
  async getEncounterResultAudit(id: number): Promise<EncounterResultAuditRead[]> {
    const response = await apiFetch(`/api/v1/admin/encounters/${id}/result-audit`);
    return response.json();
  }

  /**
   * Cross-tournament captain reports, scoped to one workspace.
   *
   * `result_status` repeats as a query param rather than joining with commas —
   * the gateway forwards every value and the backend model is a list.
   */
  async listEncounterReports(
    params: EncounterReportsQuery
  ): Promise<PaginatedResponse<EncounterReportsRow>> {
    const response = await apiFetch(
      `/api/v1/admin/encounter-reports?${buildEncounterReportsQuery(params)}`
    );
    return response.json();
  }

  /**
   * Counters behind the filter chips. Takes the same params as the list; the
   * server ignores the chip filters so each chip counts what it would select.
   */
  async getEncounterReportStats(params: EncounterReportsQuery): Promise<EncounterReportsStats> {
    const response = await apiFetch(
      `/api/v1/admin/encounter-reports/stats?${buildEncounterReportsQuery(params)}`
    );
    return response.json();
  }

  /** Parsed matches — one row per played map — across the workspace. */
  async listAdminMatches(params: AdminMatchesQuery): Promise<PaginatedResponse<AdminMatchRow>> {
    const response = await apiFetch(`/api/v1/admin/matches?${buildAdminMatchesQuery(params)}`);
    return response.json();
  }

  /**
   * One parsed match with the aggregates the list omits. Needs the workspace
   * because the endpoint 404s identically for an unknown id and for one in
   * another workspace.
   */
  async getAdminMatch(matchId: number, workspaceId: number): Promise<AdminMatchDetail> {
    const response = await apiFetch(
      `/api/v1/admin/matches/${matchId}?workspace_id=${workspaceId}`
    );
    return response.json();
  }

  async updateMatch(
    matchId: number,
    data: MatchUpdateInput
  ): Promise<{
    id: number;
    encounter_id: number;
    home_team_id: number;
    away_team_id: number;
    home_score: number;
    away_score: number;
    map_id: number;
    code: string | null;
    time: number;
    log_name: string;
  }> {
    const response = await apiFetch(`/api/v1/admin/encounters/matches/${matchId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  /**
   * Uses the same backend sync engine as the Integrations tab's "Import"
   * button (`challongeImport`): both used to hit independently-maintained
   * copies of the Challonge sync logic (parser-service vs tournament-service),
   * which had drifted -- tournament-service's copy tracks pick-ban session
   * resets on team changes and cache-invalidation reasoning that
   * parser-service's never had. Consolidated onto tournament-service's route.
   */
  async syncEncountersFromChallonge(tournamentId: number): Promise<Record<string, unknown>> {
    const response = await apiFetch(`/api/v1/admin/challonge/sync/import/${tournamentId}`, {
      method: "POST"
    });
    return response.json();
  }

  // ─── Standing Management ───────────────────────────────────────────────────

  async updateStanding(id: number, data: StandingUpdateInput): Promise<Standings> {
    const response = await apiFetch(`/api/v1/admin/standings/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteStanding(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/standings/${id}`, {
      method: "DELETE"
    });
  }

  async calculateStandings(tournamentId: number): Promise<BulkOperationResult> {
    return this.recalculateStandings(tournamentId);
  }

  async recalculateStandings(tournamentId: number): Promise<BulkOperationResult> {
    const response = await apiFetch(`/api/v1/admin/standings/recalculate/${tournamentId}`, {
      method: "POST"
    });
    const job = (await response.json()) as TournamentComputationJob;
    const completed = await this.waitForTournamentJob(job);
    return {
      success: true,
      count: Number(completed.result_json?.standing_count ?? 0)
    };
  }

  // ─── User CRUD ─────────────────────────────────────────────────────────────

  async getUsers(
    params: {
      page?: number;
      per_page?: number;
      search?: string;
      sort?: string;
      order?: string;
      tournament_id?: number;
      has_account?: boolean;
      unlinked?: boolean;
    } = {}
  ): Promise<PaginatedResponse<User>> {
    const { tournament_id, has_account, unlinked, ...list } = params;
    const response = await apiFetch("/api/v1/admin/users", {
      query: {
        ...buildAdminListQuery(list),
        ...(tournament_id != null && { tournament_id }),
        ...(has_account ? { has_account: true } : {}),
        ...(unlinked ? { unlinked: true } : {})
      }
    });
    return response.json();
  }

  async createUser(data: UserCreateInput): Promise<User> {
    const response = await apiFetch("/api/v1/admin/users", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateUser(id: number, data: UserUpdateInput): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteUser(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/users/${id}`, {
      method: "DELETE"
    });
  }

  async previewUserMerge(data: UserMergePreviewRequest): Promise<UserMergePreviewResponse> {
    const response = await apiFetch("/api/v1/admin/users/merge/preview", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async executeUserMerge(data: UserMergeExecuteRequest): Promise<UserMergeExecuteResponse> {
    const response = await apiFetch("/api/v1/admin/users/merge/execute", {
      method: "POST",
      body: data
    });
    return response.json();
  }



  // Unified social-identity management (provider-agnostic). All return the
  // refreshed User so the caller can update state in one round-trip.
  async addSocialAccount(userId: number, data: SocialAccountCreateInput): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${userId}/social`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateSocialAccount(userId: number, accountId: number, data: SocialAccountUpdateInput): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${userId}/social/${accountId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteSocialAccount(userId: number, accountId: number): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${userId}/social/${accountId}`, {
      method: "DELETE"
    });
    return response.json();
  }

  async setSocialAccountPrimary(userId: number, accountId: number): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${userId}/social/${accountId}/primary`, {
      method: "POST"
    });
    return response.json();
  }

  async verifySocialAccount(userId: number, accountId: number): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${userId}/social/${accountId}/verify`, {
      method: "POST"
    });
    return response.json();
  }

  async setSocialAccountVisibility(
    userId: number,
    accountId: number,
    data: SocialVisibilityInput
  ): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${userId}/social/${accountId}/visibility`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  // User Avatar Management
  async uploadUserAvatar(userId: number, file: File): Promise<User> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiFetch(`/api/v1/admin/users/${userId}/avatar`, {
      method: "POST",
      body: formData
    });
    return response.json();
  }

  async deleteUserAvatar(userId: number): Promise<User> {
    const response = await apiFetch(`/api/v1/admin/users/${userId}/avatar`, {
      method: "DELETE"
    });
    return response.json();
  }

  // ─── Hero CRUD ─────────────────────────────────────────────────────────────

  async getHeroes(
    params: {
      page?: number;
      per_page?: number;
      search?: string;
      role?: string;
      sort?: string;
      order?: string;
    } = {}
  ): Promise<PaginatedResponse<Hero>> {
    const response = await apiFetch("/api/v1/admin/heroes", {
      query: {
        ...(params.page != null && { page: params.page }),
        ...(params.per_page != null && { per_page: params.per_page }),
        ...(params.search && { search: params.search }),
        ...(params.role && { role: params.role }),
        ...(params.sort && { sort: params.sort }),
        ...(params.order && { order: params.order })
      }
    });
    return response.json();
  }

  async createHero(data: HeroCreateInput): Promise<Hero> {
    const response = await apiFetch("/api/v1/admin/heroes", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateHero(id: number, data: HeroUpdateInput): Promise<Hero> {
    const response = await apiFetch(`/api/v1/admin/heroes/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteHero(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/heroes/${id}`, {
      method: "DELETE"
    });
  }

  async syncHeroes(): Promise<BulkOperationResult> {
    const response = await apiFetch("/api/v1/heroes/update", {
      method: "POST"
    });
    return response.json();
  }

  // ─── Gamemode CRUD ─────────────────────────────────────────────────────────

  async getGamemodes(
    params: {
      page?: number;
      per_page?: number;
      search?: string;
      sort?: string;
      order?: string;
    } = {}
  ): Promise<PaginatedResponse<Gamemode>> {
    const response = await apiFetch("/api/v1/admin/gamemodes", {
      query: buildAdminListQuery(params)
    });
    return response.json();
  }

  async createGamemode(data: GamemodeCreateInput): Promise<Gamemode> {
    const response = await apiFetch("/api/v1/admin/gamemodes", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateGamemode(id: number, data: GamemodeUpdateInput): Promise<Gamemode> {
    const response = await apiFetch(`/api/v1/admin/gamemodes/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteGamemode(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/gamemodes/${id}`, {
      method: "DELETE"
    });
  }

  async syncGamemodes(): Promise<BulkOperationResult> {
    const response = await apiFetch("/api/v1/gamemodes/update", {
      method: "POST"
    });
    return response.json();
  }

  // ─── Map CRUD ──────────────────────────────────────────────────────────────

  async getMaps(
    params: {
      page?: number;
      per_page?: number;
      search?: string;
      gamemode_id?: number;
      in_competitive?: boolean;
      sort?: string;
      order?: string;
    } = {}
  ): Promise<PaginatedResponse<MapRead>> {
    const response = await apiFetch("/api/v1/admin/maps", {
      query: {
        ...(params.page != null && { page: params.page }),
        ...(params.per_page != null && { per_page: params.per_page }),
        ...(params.search && { search: params.search }),
        ...(params.gamemode_id != null && { gamemode_id: params.gamemode_id }),
        // `!= null`, not truthiness: `false` is a real filter value (casual pool).
        ...(params.in_competitive != null && { in_competitive: params.in_competitive }),
        ...(params.sort && { sort: params.sort }),
        ...(params.order && { order: params.order })
      }
    });
    return response.json();
  }

  async createMap(data: MapCreateInput): Promise<MapRead> {
    const response = await apiFetch("/api/v1/admin/maps", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateMap(id: number, data: MapUpdateInput): Promise<MapRead> {
    const response = await apiFetch(`/api/v1/admin/maps/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteMap(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/maps/${id}`, {
      method: "DELETE"
    });
  }

  async syncMaps(): Promise<BulkOperationResult> {
    const response = await apiFetch("/api/v1/maps/update", {
      method: "POST"
    });
    return response.json();
  }

  // ─── Catalog aliases (superuser) ───────────────────────────────────────────

  /**
   * Names the log parser could not resolve, worst offenders first. Open misses
   * only unless `include_resolved` asks for the dismissed ones too.
   */
  async getCatalogAliasMisses(
    params: CatalogAliasMissQuery = {}
  ): Promise<PaginatedResponse<CatalogAliasMissRead>> {
    const response = await apiFetch("/api/v1/admin/catalog-aliases/misses", {
      query: {
        ...(params.page != null && { page: params.page }),
        ...(params.per_page != null && { per_page: params.per_page }),
        ...(params.entity_type && { entity_type: params.entity_type }),
        ...(params.include_resolved && { include_resolved: params.include_resolved })
      }
    });
    return response.json();
  }

  /**
   * Appends the alias to the entity and closes the miss in one transaction —
   * the union happens server-side so two admins cannot clobber each other.
   */
  async attachCatalogAlias(data: CatalogAliasAttachInput): Promise<void> {
    await apiFetch("/api/v1/admin/catalog-aliases/attach", {
      method: "POST",
      body: data
    });
  }

  /** Marks the miss resolved without touching any entity. */
  async dismissCatalogAliasMiss(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/catalog-aliases/misses/${id}/dismiss`, {
      method: "POST"
    });
  }

  // ─── Achievement CRUD ──────────────────────────────────────────────────────

  async getAchievements(
    params: {
      page?: number;
      per_page?: number;
      search?: string;
      sort?: string;
      order?: string;
    } = {}
  ): Promise<PaginatedResponse<Achievement>> {
    const response = await apiFetch("/api/v1/admin/achievements", {
      query: params
    });
    return response.json();
  }

  async getAchievementRegistry(): Promise<{ entries: AchievementRegistryEntry[] }> {
    const response = await apiFetch("/api/v1/admin/achievements/registry");
    return response.json();
  }

  async createAchievement(data: AchievementCreateInput): Promise<Achievement> {
    const response = await apiFetch("/api/v1/admin/achievements", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateAchievement(id: number, data: AchievementUpdateInput): Promise<Achievement> {
    const response = await apiFetch(`/api/v1/admin/achievements/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteAchievement(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/achievements/${id}`, {
      method: "DELETE"
    });
  }

  async calculateAchievements(
    slugs?: string[],
    tournamentId?: number
  ): Promise<BulkOperationResult> {
    const url = tournamentId
      ? `/api/v1/achievement/calculate/${tournamentId}`
      : "/api/v1/achievement/calculate";
    const response = await apiFetch(url, {
      method: "POST",
      body: { slugs, ensure_created: true }
    });
    return response.json();
  }

  // ─── Achievement Rule Engine ────────────────────────────────────────────────

  async getAchievementRules(
    workspaceId: number,
    params: { category?: string; enabled?: boolean } = {}
  ): Promise<AchievementRule[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules`, {
      query: params
    });
    return response.json();
  }

  async getAchievementRule(workspaceId: number, ruleId: number): Promise<AchievementRule> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/${ruleId}`
    );
    return response.json();
  }

  async createAchievementRule(
    workspaceId: number,
    data: AchievementRuleCreateInput
  ): Promise<AchievementRule> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateAchievementRule(
    workspaceId: number,
    ruleId: number,
    data: AchievementRuleUpdateInput
  ): Promise<AchievementRule> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/${ruleId}`,
      { method: "PATCH", body: data }
    );
    return response.json();
  }

  async getAchievementRuleUsers(
    workspaceId: number,
    ruleId: number,
    params: {
      page?: number;
      per_page?: number;
      tournament_id?: number;
      sort?: string;
      order?: string;
    } = {}
  ): Promise<{
    page: number;
    per_page: number;
    total: number;
    results: {
      user_id: number;
      user_name: string;
      count: number;
      last_tournament_id: number | null;
      last_match_id: number | null;
      first_qualified: string | null;
    }[];
  }> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/${ruleId}/users`,
      { query: { page: params.page ?? 1, per_page: params.per_page ?? 30, ...params } }
    );
    return response.json();
  }

  async deleteAchievementRule(workspaceId: number, ruleId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/${ruleId}`, {
      method: "DELETE"
    });
  }

  async validateConditionTree(
    workspaceId: number,
    conditionTree: Record<string, unknown>
  ): Promise<ConditionTreeValidateResponse> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/validate`,
      { method: "POST", body: { condition_tree: conditionTree } }
    );
    return response.json();
  }

  async testAchievementRule(
    workspaceId: number,
    ruleId: number,
    tournamentId?: number
  ): Promise<{ rule_slug: string; qualifying_count: number; sample: number[][] }> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/${ruleId}/test`,
      { query: tournamentId ? { tournament_id: tournamentId } : {} }
    );
    return response.json();
  }

  async evaluateAchievements(
    workspaceId: number,
    params: { tournament_id?: number; rule_ids?: number[] } = {}
  ): Promise<EvaluationRunRead> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/evaluate`,
      { method: "POST", body: params }
    );
    return response.json();
  }

  async getEvaluationRuns(workspaceId: number): Promise<EvaluationRunRead[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/runs`);
    return response.json();
  }

  async seedAchievementRules(workspaceId: number): Promise<SeedResultRead> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/seed`, {
      method: "POST"
    });
    return response.json();
  }

  async hardResetAchievementRules(workspaceId: number): Promise<HardResetResultRead> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/reset`, {
      method: "POST"
    });
    return response.json();
  }

  async exportAchievementRules(
    workspaceId: number
  ): Promise<{ blob: Blob; filename: string; data: AchievementRuleExportEnvelope }> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/export`);
    const blob = await response.blob();
    const filename =
      response.headers.get("Content-Disposition")?.match(/filename=\"?([^"]+)\"?/)?.[1] ??
      `achievements-workspace-${workspaceId}.json`;
    const data = JSON.parse(await blob.text()) as AchievementRuleExportEnvelope;
    return {
      blob: new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }),
      filename,
      data,
    };
  }

  async importAchievementRules(
    workspaceId: number,
    data: AchievementRuleExportEnvelope
  ): Promise<AchievementRuleImportResult> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/import`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async getAchievementLibraryWorkspaces(
    workspaceId: number
  ): Promise<AchievementLibraryWorkspace[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/library/workspaces`
    );
    return response.json();
  }

  async getAchievementLibraryRules(
    workspaceId: number,
    sourceWorkspaceId: number
  ): Promise<AchievementLibraryRule[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/library`, {
      query: { source_workspace_id: sourceWorkspaceId }
    });
    return response.json();
  }

  async importAchievementLibraryRules(
    workspaceId: number,
    data: { source_workspace_id: number; slugs: string[] }
  ): Promise<AchievementRuleImportResult> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/library/import`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async getConditionTypes(): Promise<ConditionTypeInfo[]> {
    const response = await apiFetch("/api/v1/admin/ws/0/achievements/rules/condition-types");
    return response.json();
  }

  async getAchievementOverrides(workspaceId: number): Promise<AchievementOverrideRead[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/overrides`);
    return response.json();
  }

  async createAchievementOverride(
    workspaceId: number,
    data: AchievementOverrideCreateInput
  ): Promise<AchievementOverrideRead> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/overrides`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async deleteAchievementOverride(workspaceId: number, overrideId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/overrides/${overrideId}`, {
      method: "DELETE"
    });
  }

  // ─── Asset Upload ──────────────────────────────────────────────────────────

  async uploadAchievementImage(
    slug: string,
    file: File,
    workspaceId?: number
  ): Promise<{ key: string; public_url: string }> {
    const formData = new FormData();
    formData.append("file", file);
    const query = workspaceId ? { workspace_id: workspaceId } : {};
    const response = await apiFetch(`/api/v1/assets/achievements/${slug}`, {
      method: "POST",
      body: formData,
      query
    });
    return response.json();
  }

  // ─── Match Logs ────────────────────────────────────────────────────────────

  async processMatchLogs(tournamentId: number, file?: File): Promise<BulkOperationResult> {
    if (file) {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("tournament_id", tournamentId.toString());

      const response = await apiFetch("/api/v1/logs/upload", {
        method: "POST",
        body: formData
      });
      return response.json();
    } else {
      const response = await apiFetch("/api/v1/logs/process", {
        method: "POST",
        body: { tournament_id: tournamentId }
      });
      return response.json();
    }
  }

  // ─── Discord Channel Sync ─────────────────────────────────────────────────

  async getDiscordChannel(tournamentId: number): Promise<DiscordChannelRead | null> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/discord-channel`);
    if (response.status === 404) return null;
    const text = await response.text();
    if (!text || text === "null") return null;
    return JSON.parse(text);
  }

  async setDiscordChannel(
    tournamentId: number,
    data: DiscordChannelInput
  ): Promise<DiscordChannelRead> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/discord-channel`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async backfillDiscordChannel(tournamentId: number): Promise<Record<string, unknown>> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/discord-channel/backfill`, {
      method: "POST"
    });
    return response.json();
  }

  async deleteDiscordChannel(tournamentId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/discord-channel`, {
      method: "DELETE"
    });
  }

  // ─── Log Processing History ───────────────────────────────────────────────

  async getLogHistory(
    tournamentId?: number,
    params?: {
      encounterId?: number;
      workspaceId?: number | null;
      /** Server-side status filter; omit for every status. */
      status?: LogProcessingStatus;
      /** Server-side match across filename, error, uploader and encounter name. */
      search?: string;
      limit?: number;
      offset?: number;
    }
  ): Promise<LogHistoryResponse> {
    const search = params?.search?.trim();
    const response = await apiFetch("/api/v1/admin/logs/history", {
      query: {
        ...(tournamentId != null && { tournament_id: tournamentId }),
        ...(params?.encounterId != null && { encounter_id: params.encounterId }),
        ...(params?.workspaceId != null && { workspace_id: params.workspaceId }),
        ...(params?.status && { status: params.status }),
        ...(search && { search }),
        limit: params?.limit ?? 50,
        offset: params?.offset ?? 0
      }
    });
    return response.json();
  }

  async getLogStats(
    tournamentId?: number,
    params?: { encounterId?: number; workspaceId?: number | null }
  ): Promise<LogProcessingStats> {
    const response = await apiFetch("/api/v1/admin/logs/stats", {
      query: {
        ...(tournamentId != null && { tournament_id: tournamentId }),
        ...(params?.encounterId != null && { encounter_id: params.encounterId }),
        ...(params?.workspaceId != null && { workspace_id: params.workspaceId })
      }
    });
    return response.json();
  }

  async uploadMatchLogs(params: {
    tournamentId: number;
    files: File[];
    encounterId?: number | null;
  }): Promise<LogUploadResponse> {
    const formData = new FormData();
    formData.append("tournament_id", params.tournamentId.toString());
    if (params.encounterId != null) {
      formData.append("encounter_id", params.encounterId.toString());
    }
    for (const file of params.files) {
      formData.append("files[]", file);
    }

    const response = await apiFetch("/api/v1/admin/logs/upload", {
      method: "POST",
      body: formData
    });
    return response.json();
  }

  async retryLogRecord(recordId: number): Promise<LogProcessingRecord> {
    const response = await apiFetch(`/api/v1/admin/logs/${recordId}/retry`, { method: "POST" });
    return response.json();
  }

  async processAllTournamentLogs(tournamentId: number): Promise<{ message: string }> {
    const response = await apiFetch(`/api/v1/logs/${tournamentId}`, { method: "POST" });
    return response.json();
  }

  // ─── Tournament Status ──────────────────────────────────────────────────────

  async transitionTournamentStatus(
    id: number,
    data: TournamentStatusTransitionInput
  ): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}/status`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  // ─── Stage Management ───────────────────────────────────────────────────────

  async getStages(tournamentId: number): Promise<Stage[]> {
    const response = await apiFetch(`/api/v1/admin/stages/tournament/${tournamentId}`);
    return response.json();
  }

  async getStage(stageId: number): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}`);
    return response.json();
  }

  async createStage(tournamentId: number, data: StageCreateInput): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/tournament/${tournamentId}`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateStage(stageId: number, data: StageUpdateInput): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteStage(stageId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/stages/${stageId}`, { method: "DELETE" });
  }

  /**
   * The round numbers `stageId`'s bracket has, or will have. Elimination
   * rounds are not a plain `1..max_rounds` sequence -- double elimination's
   * lower bracket uses negative numbers, and single elimination's round
   * count depends on team count, not the stage's independently-set
   * `max_rounds`. Before the bracket exists this predicts the same numbers
   * the real generator will produce from the stage's planned team inputs;
   * empty when the stage type has no bracket shape or fewer than two teams
   * are wired in yet.
   */
  async getStagePlannedRounds(stageId: number): Promise<number[]> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/planned-rounds`);
    const data: { rounds: number[] } = await response.json();
    return data.rounds;
  }

  /**
   * The bracket `stageId` would generate, straight from the generator: real
   * pairings, seed order, advancement edges and per-round best-of, with
   * skeleton-local ids because nothing is written. Empty when the stage is not
   * a bracket, or fewer than two teams are wired in and none are projected.
   */
  async getStageBracketPreview(stageId: number): Promise<StageBracketPreviewMatch[]> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/bracket-preview`);
    const data: { matches: StageBracketPreviewMatch[] } = await response.json();
    return data.matches;
  }

  async mergeGroupStages(stageId: number, data: StageMergeGroupStagesInput): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/merge-group-stages`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async createStageItem(stageId: number, data: StageItemCreateInput): Promise<StageItem> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/items`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateStageItem(
    stageItemId: number,
    data: { name?: string; type?: StageItemType; order?: number; advance_count?: number | null }
  ): Promise<StageItem> {
    const response = await apiFetch(`/api/v1/admin/stages/items/${stageItemId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteStageItem(stageItemId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/stages/items/${stageItemId}`, { method: "DELETE" });
  }

  async createStageItemInput(
    stageItemId: number,
    data: StageItemInputCreateInput
  ): Promise<StageItemInput> {
    const response = await apiFetch(`/api/v1/admin/stages/items/${stageItemId}/inputs`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async updateStageItemInput(
    inputId: number,
    data: StageItemInputUpdateInput
  ): Promise<StageItemInput> {
    const response = await apiFetch(`/api/v1/admin/stages/items/inputs/${inputId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async activateStage(stageId: number): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/activate`, {
      method: "POST"
    });
    return response.json();
  }

  async deactivateStage(stageId: number): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/deactivate`, {
      method: "POST"
    });
    return response.json();
  }

  async generateBracket(stageId: number): Promise<{ generated: number }> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/generate`, {
      method: "POST"
    });
    const job = (await response.json()) as TournamentComputationJob;
    const completed = await this.waitForTournamentJob(job);
    return { generated: Number(completed.result_json?.generated ?? 0) };
  }

  async applyStageBestOf(stageId: number): Promise<{ updated: number }> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/apply-best-of`, {
      method: "POST"
    });
    return response.json();
  }

  async autoWireStage(stageId: number): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/auto-wire`, {
      method: "POST"
    });
    return response.json();
  }

  async wireFromGroups(
    stageId: number,
    data: {
      source_stage_id: number;
      top: number;
      top_lb?: number;
      mode?: "cross" | "snake";
    }
  ): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/wire-from-groups`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async activateAndGenerateStage(
    stageId: number,
    opts?: { force?: boolean }
  ): Promise<{ generated: number }> {
    const qs = opts?.force ? "?force=true" : "";
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/activate-and-generate${qs}`,
      { method: "POST" }
    );
    const job = (await response.json()) as TournamentComputationJob;
    const completed = await this.waitForTournamentJob(job);
    return { generated: Number(completed.result_json?.generated ?? 0) };
  }

  async seedTeams(
    stageId: number,
    data: {
      team_ids: number[];
      mode?: "snake_sr" | "by_total_sr" | "random";
    }
  ): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/seed-teams`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async getStagesProgress(tournamentId: number): Promise<
    {
      stage_id: number;
      name: string;
      stage_type: string;
      is_active: boolean;
      is_completed: boolean;
      total: number;
      completed: number;
      items: {
        stage_item_id: number;
        name: string;
        total: number;
        completed: number;
        is_completed: boolean;
      }[];
    }[]
  > {
    const response = await apiFetch(`/api/v1/admin/stages/tournament/${tournamentId}/progress`, {
      method: "GET"
    });
    return response.json();
  }

  // ─── Pick-Ban Sessions (live-session admin overrides only; config CRUD
  // moved to PickBanConfig -- see pickBanService.upsertConfig) ────────────────

  /** Drop the encounter's pick-ban session + pool for `kind` and re-create
   * them (re-resolves seeds). */
  async resetPickBanSession(encounterId: number, kind: PickBanKind): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-session/reset`, {
      method: "POST",
      body: { kind }
    });
    return response.json();
  }

  /** Perform a ban/pick/protect on behalf of a side (admin override). */
  async adminPickBanAct(
    encounterId: number,
    data: { kind: PickBanKind; side: "home" | "away"; item_id: number; action: "pick" | "ban" | "protect" }
  ): Promise<{ id: number; item_id: number; status: string; picked_by: string | null }> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-act`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** Name who opens the round a `result_loser_choice` rotation is holding, on
   * behalf of a losing captain who is not there to name it (admin override). */
  async adminPickBanElectOpener(
    encounterId: number,
    data: { kind: PickBanKind; first_side: "home" | "away" }
  ): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-elect-opener`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  // ─── Challonge Sync ─────────────────────────────────────────────────────────

  async challongeImport(tournamentId: number, dryRun = false): Promise<Record<string, unknown>> {
    const response = await apiFetch(`/api/v1/admin/challonge/sync/import/${tournamentId}`, {
      method: "POST",
      query: dryRun ? { dry_run: true } : undefined
    });
    return response.json();
  }

  async challongeExport(tournamentId: number): Promise<Record<string, unknown>> {
    const response = await apiFetch(`/api/v1/admin/challonge/sync/export/${tournamentId}`, {
      method: "POST"
    });
    return response.json();
  }

  async challongePushResult(encounterId: number): Promise<{ status: string }> {
    const response = await apiFetch(`/api/v1/admin/challonge/sync/push-result/${encounterId}`, {
      method: "POST"
    });
    return response.json();
  }

  async challongeSyncLog(tournamentId: number, limit = 50): Promise<ChallongeSyncLogEntry[]> {
    const response = await apiFetch(`/api/v1/admin/challonge/sync/log/${tournamentId}`, {
      query: { limit }
    });
    return response.json();
  }

  // ─── Global Settings (superuser) ──────────────────────────────────────────

  async getSettings(): Promise<SettingRead[]> {
    const response = await apiFetch("/api/v1/admin/settings", { skipWorkspace: true });
    return response.json();
  }

  async getSetting(key: string): Promise<SettingRead> {
    const response = await apiFetch(`/api/v1/admin/settings/${key}`, { skipWorkspace: true });
    return response.json();
  }

  async updateSetting(key: string, data: SettingUpsertInput): Promise<SettingRead> {
    const response = await apiFetch(`/api/v1/admin/settings/${key}`, {
      method: "PUT",
      body: data,
      skipWorkspace: true
    });
    return response.json();
  }

  // ─── OverFast rank collection ─────────────────────────────────────────────
  // `workspace_id` is injected (no `skipWorkspace`): it is the RBAC scope these
  // endpoints authorize against, so dropping it demands the GLOBAL
  // `rank.read`/`update` and locks out a workspace owner/admin holding it only
  // in their own workspace. It also scopes the rows to that workspace.

  async getRankCollectionStatus(userId: number): Promise<RankCollectionStatusRow[]> {
    const response = await apiFetch(`/api/v1/admin/rank/users/${userId}/collection`);
    return response.json();
  }

  async triggerRankCollection(data: CollectTriggerInput): Promise<CollectTriggerResult> {
    const response = await apiFetch("/api/v1/admin/rank/collect", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async getRankCollectionStats(): Promise<RankCollectionStats> {
    const response = await apiFetch("/api/v1/admin/rank/stats");
    return response.json();
  }

  async getRankFetchLog(params: RankFetchLogQuery = {}): Promise<RankFetchLogRow[]> {
    const response = await apiFetch("/api/v1/admin/rank/fetch-log", {
      query: {
        status: params.status,
        source: params.source,
        before_id: params.before_id,
        limit: params.limit ?? 50
      }
    });
    return response.json();
  }

  async reenableDisabledRankCollection(
    onlyPreviouslySucceeded = false
  ): Promise<{ reenabled: number }> {
    const response = await apiFetch("/api/v1/admin/rank/reenable-disabled", {
      method: "POST",
      body: { only_previously_succeeded: onlyPreviouslySucceeded }
    });
    return response.json();
  }

  // ─── Subscription collection ───────────────────────────────────────────────
  // `workspace_id` is injected (no `skipWorkspace`): it is the RBAC scope these
  // endpoints authorize against, so dropping it demands the GLOBAL
  // `subscription.read`/`update` and locks out a workspace owner/admin holding
  // it only in their own workspace. It also scopes the rows to that workspace.

  async getSubscriptionCollectionStats(): Promise<SubscriptionCollectionStats> {
    const response = await apiFetch("/api/v1/admin/subscriptions/stats");
    return response.json();
  }

  async getSubscriptionCheckLog(
    params: SubscriptionCheckLogQuery = {}
  ): Promise<SubscriptionCheckLogRow[]> {
    const response = await apiFetch("/api/v1/admin/subscriptions/check-log", {
      query: {
        state: params.state,
        source: params.source,
        provider: params.provider,
        user_id: params.user_id,
        before_id: params.before_id,
        limit: params.limit ?? 50
      }
    });
    return response.json();
  }

  async getSubscriptionCollectionStatus(userId: number): Promise<SubscriptionUserCollectionRow[]> {
    const response = await apiFetch(`/api/v1/admin/subscriptions/users/${userId}/collection`);
    return response.json();
  }

  async triggerSubscriptionCollection(
    data: SubscriptionCollectTriggerInput
  ): Promise<SubscriptionCollectTriggerResult> {
    const response = await apiFetch("/api/v1/admin/subscriptions/collect", {
      method: "POST",
      body: data
    });
    return response.json();
  }

  // ─── Twitch stream poller ──────────────────────────────────────────────────

  /**
   * Poller health. Note the domain: `/api/streams`, not `/api/v1`, so
   * `domainBehavior` gives it `no-store` (no cache-policy dance) but still
   * injects `workspace_id` by default — hence the explicit `skipWorkspace`.
   * There is one poller and one Redis key behind this, so the read is
   * platform-wide and authorizes against the GLOBAL `stream.read`; sending a
   * workspace would be a scope the endpoint does not have.
   */
  async getStreamPollHealth(): Promise<StreamPollHealth> {
    const response = await apiFetch("/api/streams/health", { skipWorkspace: true });
    return response.json();
  }

  // ─── Platform audit log ────────────────────────────────────────────────────

  /**
   * One feed for "who did this", scoped by the ambient workspace.
   *
   * `workspace_id` rides the usual injection because it IS the RBAC scope the
   * endpoint authorizes against — and the scope is applied first and
   * unconditionally, so `entity_type`/`entity_id`/`actor_user_id` narrow inside
   * it rather than reaching around it. Only a superuser may drop it
   * (`allWorkspaces`), which is also the only way platform rows
   * (`workspace_id IS NULL`) come back at all.
   */
  async listAudit(params: AuditLogQuery = {}): Promise<PaginatedResponse<AuditLogRead>> {
    const { allWorkspaces, ...query } = params;
    const response = await apiFetch("/api/v1/admin/audit", {
      skipWorkspace: allWorkspaces === true,
      query
    });
    return response.json();
  }
}

const adminService = new AdminService();
export default adminService;
