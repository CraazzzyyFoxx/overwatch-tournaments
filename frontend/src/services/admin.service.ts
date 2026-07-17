import { apiFetch } from "@/lib/api-fetch";
import { PaginatedResponse } from "@/types/pagination.types";
import {
  Tournament,
  Standings,
  Stage,
  StageItem,
  StageItemInput,
  StageItemType
} from "@/types/tournament.types";
import { Team, Player } from "@/types/team.types";
import { Encounter } from "@/types/encounter.types";
import { User } from "@/types/user.types";
import { Hero } from "@/types/hero.types";
import { Achievement } from "@/types/achievement.types";
import { Gamemode } from "@/types/gamemode.types";
import { MapRead } from "@/types/map.types";
import {
  TournamentCreateInput,
  TournamentUpdateInput,
  TournamentPreviewAccessEntry,
  TournamentStatusTransitionInput,
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
  CsvUserImportParams,
  UserMergePreviewRequest,
  UserMergePreviewResponse,
  UserMergeExecuteRequest,
  UserMergeExecuteResponse,
  DiscordChannelRead,
  DiscordChannelInput,
  LogHistoryResponse,
  LogProcessingRecord,
  LogUploadResponse,
  QueueDepth,
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
  RankCollectionStats
} from "@/types/admin.types";

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
    number: number;
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

  async bulkCreateTeamsFromBalancer(
    tournamentId: number,
    file: File
  ): Promise<BulkOperationResult> {
    const formData = new FormData();
    formData.append("file", file);
    formData.append("tournament_id", tournamentId.toString());

    const response = await apiFetch("/api/v1/teams/create/balancer", {
      method: "POST",
      body: formData
    });
    return response.json();
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

  async confirmEncounterResult(
    id: number
  ): Promise<{ id: number; result_status: string; status: string }> {
    const response = await apiFetch(`/api/v1/admin/encounters/${id}/confirm-result`, {
      method: "POST"
    });
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

  async syncEncountersFromChallonge(tournamentId: number): Promise<BulkOperationResult> {
    const response = await apiFetch("/api/v1/encounter/challonge", {
      method: "POST",
      query: { tournament_id: tournamentId }
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
    } = {}
  ): Promise<PaginatedResponse<User>> {
    const response = await apiFetch("/api/v1/admin/users", {
      query: {
        ...(params.page != null && { page: params.page }),
        ...(params.per_page != null && { per_page: params.per_page }),
        ...(params.search && { search: params.search }),
        ...(params.sort && { sort: params.sort }),
        ...(params.order && { order: params.order })
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

  async bulkCreateUsersFromCsv(
    params: CsvUserImportParams,
    file?: File
  ): Promise<BulkOperationResult> {
    const formData = new FormData();
    if (file) {
      formData.append("data", file);
    }

    const hasDiscord = params.discord_row != null;
    const hasTwitch = params.twitch_row != null;
    const hasSmurf = params.smurf_row != null;

    const query: Record<string, unknown> = {
      battle_tag_row: params.battle_tag_row,
      discord_row: params.discord_row ?? 1,
      twitch_row: params.twitch_row ?? 1,
      smurf_row: params.smurf_row ?? 1,
      has_discord: hasDiscord,
      has_twitch: hasTwitch,
      has_smurf: hasSmurf
    };
    if (params.start_row != null) query.start_row = params.start_row;
    if (params.delimiter) query.delimiter = params.delimiter;
    if (params.sheet_url) query.sheet_url = params.sheet_url;

    const response = await apiFetch("/api/v1/user/create/csv", {
      method: "POST",
      body: formData,
      query
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
      query: {
        ...(params.page != null && { page: params.page }),
        ...(params.per_page != null && { per_page: params.per_page }),
        ...(params.search && { search: params.search }),
        ...(params.sort && { sort: params.sort }),
        ...(params.order && { order: params.order })
      }
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

  async deleteDiscordChannel(tournamentId: number): Promise<void> {
    await apiFetch(`/api/v1/admin/tournaments/${tournamentId}/discord-channel`, {
      method: "DELETE"
    });
  }

  // ─── Log Processing History ───────────────────────────────────────────────

  async getLogHistory(
    tournamentId?: number,
    params?: { encounterId?: number; workspaceId?: number | null; limit?: number; offset?: number }
  ): Promise<LogHistoryResponse> {
    const response = await apiFetch("/api/v1/admin/logs/history", {
      query: {
        ...(tournamentId != null && { tournament_id: tournamentId }),
        ...(params?.encounterId != null && { encounter_id: params.encounterId }),
        ...(params?.workspaceId != null && { workspace_id: params.workspaceId }),
        limit: params?.limit ?? 50,
        offset: params?.offset ?? 0
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

  async getQueueStatus(): Promise<QueueDepth[]> {
    const response = await apiFetch("/api/v1/admin/logs/queue-status");
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
    data: { name?: string; type?: StageItemType; order?: number }
  ): Promise<StageItem> {
    const response = await apiFetch(`/api/v1/admin/stages/items/${stageItemId}`, {
      method: "PATCH",
      body: data
    });
    return response.json();
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

  async generateBracket(stageId: number): Promise<{ generated: number }> {
    const response = await apiFetch(`/api/v1/admin/stages/${stageId}/generate`, {
      method: "POST"
    });
    const job = (await response.json()) as TournamentComputationJob;
    const completed = await this.waitForTournamentJob(job);
    return { generated: Number(completed.result_json?.generated ?? 0) };
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

  async bulkUpdateEncounters(data: {
    encounter_ids: number[];
    status?: string;
    home_score?: number;
    away_score?: number;
    reset_scores?: boolean;
  }): Promise<{
    updated: number;
    newly_completed: number;
    tournaments_recalculated: number[];
  }> {
    const response = await apiFetch("/api/v1/admin/encounters/bulk", {
      method: "PATCH",
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

  // ─── Admin Map Pool ─────────────────────────────────────────────────────────

  async assignMapPool(encounterId: number, mapIds: number[]): Promise<{ assigned: number }> {
    const response = await apiFetch(`/api/v1/admin/encounters/${encounterId}/map-pool`, {
      method: "POST",
      body: { map_ids: mapIds }
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

  // ─── OverFast rank collection (superuser/admin) ───────────────────────────

  async getRankCollectionStatus(userId: number): Promise<RankCollectionStatusRow[]> {
    const response = await apiFetch(`/api/v1/admin/rank/users/${userId}/collection`, {
      skipWorkspace: true
    });
    return response.json();
  }

  async triggerRankCollection(data: CollectTriggerInput): Promise<CollectTriggerResult> {
    const response = await apiFetch("/api/v1/admin/rank/collect", {
      method: "POST",
      body: data,
      skipWorkspace: true
    });
    return response.json();
  }

  async getRankCollectionStats(): Promise<RankCollectionStats> {
    const response = await apiFetch("/api/v1/admin/rank/stats", { skipWorkspace: true });
    return response.json();
  }

  async getRankFetchLog(params: RankFetchLogQuery = {}): Promise<RankFetchLogRow[]> {
    const response = await apiFetch("/api/v1/admin/rank/fetch-log", {
      query: {
        status: params.status,
        source: params.source,
        before_id: params.before_id,
        limit: params.limit ?? 50
      },
      skipWorkspace: true
    });
    return response.json();
  }

  async reenableDisabledRankCollection(
    onlyPreviouslySucceeded = false
  ): Promise<{ reenabled: number }> {
    const response = await apiFetch("/api/v1/admin/rank/reenable-disabled", {
      method: "POST",
      body: { only_previously_succeeded: onlyPreviouslySucceeded },
      skipWorkspace: true
    });
    return response.json();
  }
}

const adminService = new AdminService();
export default adminService;
