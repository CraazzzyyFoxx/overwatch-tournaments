import { apiFetch } from "@/lib/api/fetch";
import { teamFormatPayload, type TeamFormatRead, type TeamFormatWrite } from "@/lib/roster/team-format";
import { PaginatedResponse } from "@/types/pagination.types";
import {
  Tournament,
  Standings,
  Stage,
  StageItem,
  StageItemInput,
  StageItemType,
  StageNodeStatus,
  PickBanKind,
  PickBanState,
  PickBanSubmissionItem,
  TournamentImageSlot
} from "@/types/tournament.types";
import { Team, Player } from "@/types/team.types";
import { Encounter, Match } from "@/types/encounter.types";
import { User } from "@/types/user.types";
import type {
  CatalogEntityRead,
  CatalogEntityWrite,
  CatalogKind,
  CatalogListFilters,
  CatalogSyncState
} from "@/types/catalog.types";
import type {
  TournamentLink,
  TournamentLinkCreateInput,
  TournamentLinkUpdateInput
} from "@/types/stream.types";
import {
  TournamentCreateInput,
  TournamentUpdateInput,
  TournamentPreviewAccessEntry,
  TournamentReadiness,
  StageCreateInput,
  PlayerStanding,
  PlayerStandingPin,
  QualificationLock,
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
  EncounterSwapSlotInput,
  EncounterSlotSwapRead,
  MatchUpdateInput,
  StandingUpdateInput,
  UserCreateInput,
  UserUpdateInput,
  SocialAccountCreateInput,
  SocialAccountUpdateInput,
  SocialVisibilityInput,
  CatalogAliasAttachInput,
  CatalogAliasMissQuery,
  CatalogAliasMissRead,
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
  GameObservationRead,
  DiscordChannelInput,
  VoiceSettings,
  VoiceStatus,
  LogBindRequest,
  LogBindResponse,
  LogHistoryResponse,
  LogProcessingRecord,
  LogProcessingStats,
  LogProcessingStatus,
  LogRetryRequest,
  LogUploadResponse,
  LogUploadScope,
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
  StreamPollTick,
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
  BracketTemplate,
  BracketTemplateRead,
  PregameRoomsRead,
  PregameRoomHistoryRead,
} from "@/types/admin.types";
import type { AdminDashboard, DashboardTrends } from "@/types/admin-dashboard.types";
import type { FlowNodeRead, FlowNodeScheduleEntry, FlowNodeStatus } from "@/types/flow.types";

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
  if (params.discipline) search.set("discipline", params.discipline);
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

  async getTournament(id: number, signal?: AbortSignal): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}`, { signal, skipWorkspace: true });
    return response.json();
  }

  /** Readiness aggregate for the hub living checklist (D13, §7.1). */
  async getTournamentReadiness(id: number): Promise<TournamentReadiness> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}/readiness`);
    return response.json();
  }

  async updateTournament(id: number, data: TournamentUpdateInput): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${id}`, { method: "PATCH", body: data });
    return response.json();
  }

  async getTournamentTeamFormat(id: number, workspaceId: number, signal?: AbortSignal): Promise<TeamFormatRead> {
    return apiFetch(`/api/v1/admin/tournaments/${id}/team-format`, {
      query: { workspace_id: workspaceId }, skipWorkspace: true, signal
    }).then(response => response.json());
  }

  async updateTournamentTeamFormat(id: number, workspaceId: number, format: TeamFormatWrite): Promise<TeamFormatRead> {
    return apiFetch(`/api/v1/admin/tournaments/${id}/team-format`, {
      method: "PUT", query: { workspace_id: workspaceId }, skipWorkspace: true, body: teamFormatPayload(format)
    }).then(response => response.json());
  }

  async deleteTournament(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/tournaments/${id}`, {
      method: "DELETE"
    });
  }

  async createTournamentWithGroups(params: {
    workspace_id: number;
    discipline: string;
    challonge_slug: string;
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

  /** Archives a `completed` tournament, or returns an archived one to `completed`; the only status an admin sets. */
  async setArchived(tournamentId: number, archived: boolean): Promise<Tournament> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/archive`, {
      method: "POST",
      body: { archived }
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

  /** The workspace's sub-roles: one game's, or every game's without `discipline` (each row names its own). */
  async getPlayerSubRoles(params: {
    workspace_id: number;
    discipline?: string;
    role?: string;
    include_inactive?: boolean;
  }, signal?: AbortSignal): Promise<PlayerSubRole[]> {
    const response = await apiFetch("/api/v1/admin/player-sub-roles", {
      query: params, signal, skipWorkspace: true
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

  /**
   * Exchange the teams held by two bracket slots in one transaction — the
   * bracket's drag-and-drop rearrange. Two PATCHes would leave a team in two
   * matches if the second failed. The server refuses settled and live matches.
   */
  async swapEncounterSlot(
    encounterId: number,
    data: EncounterSwapSlotInput
  ): Promise<EncounterSlotSwapRead> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/swap-slot`, {
      method: "POST",
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
   * The single admin result write: the standing, status, result_status and the
   * audit row move together. Names either the participations' numbers or
   * `adopt_report_team_id`, and always a `reason` for the journal.
   */
  async setEncounterResult(
    id: number,
    data: EncounterSetResultInput
  ): Promise<EncounterResultRead> {
    const response = await apiFetch(`/api/v1/admin/encounters/${id}/result`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** Un-confirm a result so it can be replayed or re-reported; the reason is journaled. */
  async reopenEncounterResult(id: number, reason: string): Promise<EncounterResultRead> {
    const response = await apiFetch(`/api/v1/admin/encounters/${id}/result/reopen`, {
      method: "POST",
      body: { reason }
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

  async updateMatch(matchId: number, data: MatchUpdateInput): Promise<Match> {
    const response = await apiFetch(`/api/v1/admin/encounters/matches/${matchId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  /**
   * Uses the same backend sync engine as the Integrations tab's "Import"
   * button (`challongeImport`): both used to hit independently-maintained
   * copies of the Challonge sync logic (stats-service vs tournament-service),
   * which had drifted -- tournament-service's copy tracks pick-ban session
   * resets on team changes and cache-invalidation reasoning that
   * stats-service's never had. Consolidated onto tournament-service's route.
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

  /**
   * Replace every pinned place of one standings table — `(stageId,
   * stage_item_id)`. Resolves once the recalculation that applies the pins has
   * finished, so a refetch afterwards already shows them.
   */
  async setStandingPins(
    stageId: number,
    body: { stage_item_id: number | null; pins: { team_id: number; position: number }[] }
  ): Promise<void> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/standing-pins`, {
      method: "PUT",
      body
    });
    const job = (await response.json()) as TournamentComputationJob;
    await this.waitForTournamentJob(job);
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

  // ─── Game catalog (admin CRUD by discipline and kind) ──────────────────────

  async listCatalogEntities(
    discipline: string,
    kind: CatalogKind,
    filters: CatalogListFilters = {},
    opts: { signal?: AbortSignal } = {}
  ): Promise<PaginatedResponse<CatalogEntityRead>> {
    const { attrs, ...rest } = filters;
    const response = await apiFetch(`/api/v1/admin/catalog/${discipline}/${kind}`, {
      signal: opts.signal,
      query: { ...rest, ...(attrs !== undefined && { attrs: JSON.stringify(attrs) }) }
    });
    return response.json();
  }

  async createCatalogEntity(
    discipline: string,
    kind: CatalogKind,
    data: CatalogEntityWrite
  ): Promise<CatalogEntityRead> {
    const response = await apiFetch(`/api/v1/admin/catalog/${discipline}/${kind}`, { method: "POST", body: data });
    return response.json();
  }

  async updateCatalogEntity(
    discipline: string,
    kind: CatalogKind,
    id: number,
    data: CatalogEntityWrite
  ): Promise<CatalogEntityRead> {
    const response = await apiFetch(`/api/v1/admin/catalog/${discipline}/${kind}/${id}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
  }

  async deleteCatalogEntity(discipline: string, kind: CatalogKind, id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/catalog/${discipline}/${kind}/${id}`, { method: "DELETE" });
  }

  /**
   * Stores an image for a catalog entity in our bucket and returns its public URL; the caller saves it as
   * `image_path`. A fresh key per upload, so a replaced image is never served from a cache.
   */
  async uploadCatalogImage(discipline: string, kind: CatalogKind, file: File): Promise<{ key: string; public_url: string }> {
    const formData = new FormData();
    formData.append("file", file);
    const suffix = crypto.randomUUID().replace(/-/g, "").slice(0, 12);
    const response = await apiFetch(`/api/v1/assets/catalog/${discipline}-${kind}-${suffix}`, {
      method: "POST",
      body: formData
    });
    return response.json();
  }

  /**
   * Every character of one discipline's catalog, for a workspace's achievement editor. A read open to the
   * workspace's achievement editors (the platform catalog list is superuser-only).
   */
  async getCatalogCharacters(workspaceId: number, discipline: string): Promise<CatalogEntityRead[]> {
    const page: PaginatedResponse<CatalogEntityRead> = await (
      await apiFetch(`/api/v1/admin/ws/${workspaceId}/catalog/${discipline}/character`, {
        query: { per_page: -1, sort: "name", order: "asc" }
      })
    ).json();
    return page.results;
  }

  /** Start pulling a discipline's catalog from its module's source (OverFast, Data Dragon) in the background; 409
   *  `catalog_sync_running` while one already runs. */
  async startCatalogSync(discipline: string): Promise<CatalogSyncState> {
    const response = await apiFetch(`/api/v1/admin/catalog-sync/${discipline}`, { method: "POST" });
    return response.json();
  }

  /** The discipline's latest sync; null when none ran in the last 15 minutes or its worker died mid-run. */
  async getCatalogSync(discipline: string): Promise<CatalogSyncState | null> {
    const response = await apiFetch(`/api/v1/admin/catalog-sync/${discipline}`);
    return response.json();
  }

  // ─── Catalog aliases (superuser) ───────────────────────────────────────────

  /**
   * Unresolved names of every discipline and kind, worst offenders first. Open misses
   * only unless `include_resolved` asks for the dismissed ones too.
   */
  async getCatalogAliasMisses(params: CatalogAliasMissQuery = {}): Promise<PaginatedResponse<CatalogAliasMissRead>> {
    const response = await apiFetch("/api/v1/admin/catalog-aliases/misses", {
      query: {
        ...(params.discipline && { discipline: params.discipline }),
        ...(params.page != null && { page: params.page }),
        ...(params.per_page != null && { per_page: params.per_page }),
        ...(params.kind && { kind: params.kind }),
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
      body: { entity_id: data.entity_id, alias: data.alias }
    });
  }

  /** Marks the miss resolved without touching any entity. */
  async dismissCatalogAliasMiss(id: number): Promise<void> {
    await apiFetch(`/api/v1/admin/catalog-aliases/misses/${id}/dismiss`, {
      method: "POST"
    });
  }

  // ─── Achievement Rule Engine ────────────────────────────────────────────────

  /** The workspace's rules: one game's, or every game's when `discipline` is `null` (each rule names its own). */
  async getAchievementRules(
    workspaceId: number,
    discipline: string | null,
    params: {
      page?: number;
      per_page?: number;
      search?: string;
      sort?: string;
      order?: string;
      category?: string;
      enabled?: boolean;
    } = {}
  ): Promise<PaginatedResponse<AchievementRule>> {
    const { category, enabled, ...list } = params;
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules`, {
      query: {
        discipline,
        ...buildAdminListQuery(list),
        ...(category != null && { category }),
        ...(enabled != null && { enabled })
      }
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
    discipline: string,
    conditionTree: Record<string, unknown>
  ): Promise<ConditionTreeValidateResponse> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/validate`,
      { method: "POST", body: { discipline, condition_tree: conditionTree } }
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
    discipline: string,
    params: { tournament_id?: number; rule_ids?: number[] } = {}
  ): Promise<EvaluationRunRead> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/evaluate`,
      { method: "POST", body: { discipline, ...params } }
    );
    return response.json();
  }

  async getEvaluationRuns(workspaceId: number): Promise<EvaluationRunRead[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/runs`);
    return response.json();
  }

  async seedAchievementRules(workspaceId: number, discipline: string): Promise<SeedResultRead> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/seed`, {
      method: "POST",
      query: { discipline }
    });
    return response.json();
  }

  async hardResetAchievementRules(workspaceId: number, discipline: string): Promise<HardResetResultRead> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/reset`, {
      method: "POST",
      query: { discipline }
    });
    return response.json();
  }

  async exportAchievementRules(
    workspaceId: number,
    discipline: string
  ): Promise<{ blob: Blob; filename: string; data: AchievementRuleExportEnvelope }> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/export`, {
      query: { discipline }
    });
    const blob = await response.blob();
    const filename =
      response.headers.get("Content-Disposition")?.match(/filename=\"?([^"]+)\"?/)?.[1] ??
      `achievements-workspace-${workspaceId}-${discipline}.json`;
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
    workspaceId: number,
    discipline: string
  ): Promise<AchievementLibraryWorkspace[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/library/workspaces`, {
      query: { discipline }
    });
    return response.json();
  }

  async getAchievementLibraryRules(
    workspaceId: number,
    sourceWorkspaceId: number,
    discipline: string
  ): Promise<AchievementLibraryRule[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/library`, {
      query: { source_workspace_id: sourceWorkspaceId, discipline }
    });
    return response.json();
  }

  async importAchievementLibraryRules(
    workspaceId: number,
    data: { source_workspace_id: number; discipline: string; slugs: string[] }
  ): Promise<AchievementRuleImportResult> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/library/import`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  async getConditionTypes(workspaceId: number, discipline: string): Promise<ConditionTypeInfo[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/rules/condition-types`, {
      query: { discipline }
    });
    return response.json();
  }

  async getAchievementOverrides(workspaceId: number, discipline: string): Promise<AchievementOverrideRead[]> {
    const response = await apiFetch(`/api/v1/admin/ws/${workspaceId}/achievements/overrides`, {
      query: { discipline }
    });
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

  // ─── Tournament voice channels ────────────────────────────────────────────

  async getVoice(tournamentId: number): Promise<VoiceStatus> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/voice`);
    return response.json();
  }

  async putVoice(tournamentId: number, data: VoiceSettings): Promise<VoiceStatus> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/voice`, {
      method: "PUT",
      body: data
    });
    return response.json();
  }

  async syncVoice(tournamentId: number): Promise<VoiceStatus> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/voice/sync`, {
      method: "POST"
    });
    return response.json();
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

  async uploadMatchLogs(params: LogUploadScope & { files: File[] }): Promise<LogUploadResponse> {
    const formData = new FormData();
    if ("customGameId" in params) {
      formData.append("custom_game_id", params.customGameId.toString());
      // Exactly one of the two: a pinned encounter or the lobby the server resolves at upload time.
      if ("lobbyIndex" in params) formData.append("lobby_index", params.lobbyIndex.toString());
      else formData.append("encounter_id", params.encounterId.toString());
    } else {
      formData.append("tournament_id", params.tournamentId.toString());
      if (params.encounterId != null) {
        formData.append("encounter_id", params.encounterId.toString());
      }
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

  /** Omitted hints preserve the job's current binding; game IDs are never series positions. */
  async retryLogRecord(recordId: number, request: LogRetryRequest = {}): Promise<LogProcessingRecord> {
    const response = await apiFetch(`/api/v1/admin/logs/${recordId}/retry`, {
      method: "POST",
      body: request
    });
    return response.json();
  }

  /**
   * Binds an awaiting_link job's stored document to one game with the operator's complete team map and
   * publishes it in the same transaction. The client never sends the document; `expected_revision` is the
   * operator's view of the target game (0 = empty) and is required when the game already has an observation.
   */
  async bindLogRecord(recordId: number, request: LogBindRequest): Promise<LogBindResponse> {
    const response = await apiFetch(`/api/v1/admin/logs/${recordId}/bind`, {
      method: "POST",
      body: request
    });
    return response.json();
  }

  /** The authoritative current observation of one game: its `revision` is the bind's `expected_revision`. */
  async getGameObservation(encounterGameId: number): Promise<GameObservationRead> {
    const response = await apiFetch(`/api/v1/admin/logs/games/${encounterGameId}/observation`);
    return response.json();
  }

  async processAllTournamentLogs(tournamentId: number): Promise<{ message: string }> {
    const response = await apiFetch(`/api/v1/logs/${tournamentId}`, { method: "POST" });
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

  /**
   * `stageId`'s bracket layout: its saved custom template, or the one its
   * format generates for the current seed counts, plus those counts.
   */
  async getStageBracketTemplate(stageId: number): Promise<BracketTemplateRead> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/bracket-template`);
    return response.json();
  }

  /**
   * Save a hand-drawn bracket. Rejected with 409 once the stage has matches and
   * with 422 when the template breaks the bracket rules — that body's
   * `details.fields[0].problems` is a `TemplateProblem[]`.
   */
  async setStageBracketTemplate(stageId: number, template: BracketTemplate): Promise<BracketTemplateRead> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/bracket-template`, {
      method: "PUT",
      body: template
    });
    return response.json();
  }

  /** Drop the custom layout and go back to the generated one. */
  async clearStageBracketTemplate(stageId: number): Promise<BracketTemplateRead> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/bracket-template`, {
      method: "DELETE"
    });
    return response.json();
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
    data: {
      name?: string;
      type?: StageItemType;
      order?: number;
    }
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

  async deleteStageItemInput(inputId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/stages/items/inputs/${inputId}`, { method: "DELETE" });
  }

  /**
   * Moves a lifecycle node (a stage's `node_id`) to `status`. The server runs the move's side effects: `ready`
   * seats the stage's inputs, `live` publishes it and generates its matches when it has none.
   */
  async transitionNode(nodeId: number, status: FlowNodeStatus): Promise<FlowNodeRead> {
    const response = await apiFetch(`/api/v1/admin/flow-nodes/${nodeId}/transition`, {
      method: "POST",
      body: { status }
    });
    return response.json();
  }

  /** Replaces a lifecycle node's schedule: one row per phase (`SCHEDULE_PHASES` of its kind) the scheduler moves it on. */
  async setNodeSchedule(nodeId: number, schedule: FlowNodeScheduleEntry[]): Promise<FlowNodeRead> {
    const response = await apiFetch(`/api/v1/admin/flow-nodes/${nodeId}/schedule`, {
      method: "PUT",
      body: { schedule }
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

  async seedTeams(
    stageId: number,
    data: {
      team_ids: number[];
      mode?: "snake_sr" | "by_total_sr" | "random" | "captain_rank";
    }
  ): Promise<Stage> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/seed-teams`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** The personal tables of every `individual_swiss` stage of the tournament (the public read). */
  async listPlayerStandings(tournamentId: number): Promise<PlayerStanding[]> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/player-standings`);
    return response.json();
  }

  /** Replaces every pin of the stage; an empty list unpins everyone. */
  async setPlayerStandingPins(
    tournamentId: number,
    stageId: number,
    pins: PlayerStandingPin[]
  ): Promise<PlayerStandingPin[]> {
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/stages/${stageId}/player-standing-pins`,
      { method: "PUT", body: { pins } }
    );
    return (await response.json()).pins;
  }

  /** Freezes the qualifiers and moves the tournament LIVE to DRAFT. */
  async lockQualification(tournamentId: number, stageId: number): Promise<QualificationLock> {
    const response = await apiFetch(
      `/api/v1/admin/tournaments/${tournamentId}/stages/${stageId}/lock-qualification`,
      { method: "POST" }
    );
    return response.json();
  }

  async getStagesProgress(tournamentId: number): Promise<
    {
      stage_id: number;
      name: string;
      stage_type: string;
      node_id: number;
      status: StageNodeStatus;
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

  /**
   * Perform one ban/pick/protect/side pick on behalf of a participation on an
   * OPEN step (admin override). `target_player_id` is required when the step
   * names an opponent player. Returns the new room state, like every other
   * pick-ban mutation.
   */
  async adminPickBanAct(
    encounterId: number,
    data: {
      kind: PickBanKind;
      encounter_team_id: number;
      item_id: number;
      action: "pick" | "ban" | "protect" | "side_pick";
      target_player_id?: number | null;
      member_id?: number | null;
    }
  ): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-act`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** Replace (and optionally lock) a participation's whole draft on a BLIND step,
   * for a captain who cannot submit it themselves. */
  async adminPickBanSubmit(
    encounterId: number,
    data: {
      kind: PickBanKind;
      encounter_team_id: number;
      items: PickBanSubmissionItem[];
      lock: boolean;
    }
  ): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-submit`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** Reopen the last revealed step for both sides — the captains' `dispute`
   * without its attempt limit, for when a reveal has to be redone. */
  async adminPickBanReopen(encounterId: number, kind: PickBanKind): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-reopen`, {
      method: "POST",
      body: { kind }
    });
    return response.json();
  }

  /** Name who opens the round a `result_loser_choice` rotation is holding, on
   * behalf of a losing captain who is not there to name it (admin override). */
  async adminPickBanElectOpener(
    encounterId: number,
    data: { kind: PickBanKind; first_team_id: number }
  ): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-elect-opener`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** The room's journal: its own events merged with the encounter's result
   * audit, newest first. Read only while an organizer has the panel open. */
  async getPregameRoomHistory(encounterId: number, limit = 200): Promise<PregameRoomHistoryRead> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/room-history`, {
      query: { limit }
    });
    return response.json();
  }

  /** Hold / release the clock on a live session: a paused session has no
   * deadline and refuses every captain write until it is resumed. */
  async adminPickBanPause(
    encounterId: number,
    data: { kind: PickBanKind; paused: boolean }
  ): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-pause`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** Give the open timed step `seconds` more, for a captain who lost their
   * connection mid-turn. Allowed while paused. */
  async adminPickBanExtend(
    encounterId: number,
    data: { kind: PickBanKind; seconds: number }
  ): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-extend`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** Cancel a session for good: hero bans stop for the rest of the series, a
   * cancelled map veto drops the series into freeplay. Undo = a reset. */
  async adminPickBanCancel(
    encounterId: number,
    data: { kind: PickBanKind; reason: string }
  ): Promise<PickBanState> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/pick-ban-cancel`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /** End the encounter against one participation: every session cancelled, every
   * unconfirmed game cancelled, the result set and confirmed in one go. `results`
   * states the exact forfeit scores; omitted, the default forfeit score applies. */
  async adminTechnicalLoss(
    encounterId: number,
    data: {
      loser_team_id: number;
      results?: { encounter_team_id: number; score: number }[];
      reason: string;
    }
  ): Promise<EncounterResultRead> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/technical-loss`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /**
   * Force one participation's readiness for a captain who cannot press the
   * button —
   * the gate that holds BOTH kinds' sessions shut, so an absent captain
   * otherwise freezes the whole room (backend:
   * `pick_ban_session.ensure_pick_ban_session`). Clearing readiness is
   * refused with a 409 once a session exists: by then the gate is behind us
   * and only a reset undoes it.
   */
  async setEncounterReadiness(
    encounterId: number,
    data: { encounter_team_id: number; ready: boolean }
  ): Promise<{ readiness: Record<string, boolean> }> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/readiness`, {
      method: "POST",
      body: data
    });
    return response.json();
  }

  /**
   * Every pre-game room of a tournament in one read: where each encounter sits
   * in the sequence, whose turn it is, and what is already overdue.
   *
   * The organizer's view of the rooms used to be "open each encounter and
   * look", which does not scale past a handful of concurrent matches — this is
   * the list that says which of them needs a human right now.
   */
  async getPregameRooms(tournamentId: number): Promise<PregameRoomsRead> {
    const response = await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/pregame-rooms`);
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

  // ─── Native rank collection ───────────────────────────────────────────────
  // `workspace_id` is injected (no `skipWorkspace`): it is the RBAC scope these
  // endpoints authorize against, so dropping it demands the GLOBAL
  // `rank.read`/`update` and locks out a workspace owner/admin holding it only
  // in their own workspace. It also scopes the rows to that workspace.
  // `discipline` picks the game's collector (OverFast for Overwatch, Riot for League).

  async getRankCollectionStatus(userId: number, discipline: string): Promise<RankCollectionStatusRow[]> {
    const response = await apiFetch(`/api/v1/admin/rank/users/${userId}/collection`, {
      query: { discipline }
    });
    return response.json();
  }

  async triggerRankCollection(discipline: string, data: CollectTriggerInput): Promise<CollectTriggerResult> {
    const response = await apiFetch("/api/v1/admin/rank/collect", {
      method: "POST",
      query: { discipline },
      body: data
    });
    return response.json();
  }

  async getRankCollectionStats(discipline: string): Promise<RankCollectionStats> {
    const response = await apiFetch("/api/v1/admin/rank/stats", { query: { discipline } });
    return response.json();
  }

  async getRankFetchLog(discipline: string, params: RankFetchLogQuery = {}): Promise<RankFetchLogRow[]> {
    const response = await apiFetch("/api/v1/admin/rank/fetch-log", {
      query: {
        discipline,
        status: params.status,
        source: params.source,
        before_id: params.before_id,
        limit: params.limit ?? 50
      }
    });
    return response.json();
  }

  async reenableDisabledRankCollection(
    discipline: string,
    onlyPreviouslySucceeded = false
  ): Promise<{ reenabled: number }> {
    const response = await apiFetch("/api/v1/admin/rank/reenable-disabled", {
      method: "POST",
      query: { discipline },
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
   * Poller health. `streams` is a live domain, so `domainBehavior` gives it
   * `no-store` (no cache-policy dance) but still injects `workspace_id` by
   * default — hence the explicit `skipWorkspace`.
   * There is one poller and one Redis key behind this, so the read is
   * platform-wide and authorizes against the GLOBAL `stream.read`; sending a
   * workspace would be a scope the endpoint does not have.
   */
  async getStreamPollHealth(): Promise<StreamPollHealth> {
    const response = await apiFetch("/api/v1/streams/health", { skipWorkspace: true });
    return response.json();
  }

  /** The last 200 recorded poll ticks, newest first. Same global gate as health. */
  async getStreamPollTicks(): Promise<StreamPollTick[]> {
    const response = await apiFetch("/api/v1/streams/health/ticks", { skipWorkspace: true });
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

  // ─── Organizer dashboard ───────────────────────────────────────────────────

  /** The admin home of the ambient workspace: phase cards, timeline, work queue, backlog. */
  async getDashboard(): Promise<AdminDashboard> {
    const response = await apiFetch("/api/v1/admin/dashboard");
    return response.json();
  }

  /** The last ten finished tournaments of the ambient workspace, every game. */
  async getDashboardTrends(): Promise<DashboardTrends> {
    const response = await apiFetch("/api/v1/admin/dashboard/trends");
    return response.json();
  }
}

const adminService = new AdminService();
export default adminService;
