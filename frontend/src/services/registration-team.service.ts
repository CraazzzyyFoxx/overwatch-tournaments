import { apiFetch } from "@/lib/api-fetch";
import type {
  RegistrationFreeAgentListResponse,
  RegistrationTeam,
  RegistrationTeamAcceptInput,
  RegistrationTeamCreateInput,
  RegistrationTeamExportResult,
  RegistrationTeamInviteCreated,
  RegistrationTeamInviteHistoryResponse,
  RegistrationTeamInviteInput,
  RegistrationTeamInviteOfferListResponse,
  RegistrationTeamInvitePreview,
  RegistrationTeamListResponse,
} from "@/types/registration-team.types";

/**
 * The eleven team-registration flows plus the two list reads.
 *
 * Note the two different path prefixes, which mirror who owns each operation:
 * team CREATION is scoped under its tournament, while everything afterwards is
 * scoped by team or invite id — a captain editing their roster does not need to
 * restate which tournament it belongs to, and the server resolves it from the row.
 *
 * Accept/decline deliberately take the invite reference in the BODY, never the
 * path: a raw token in a URL lands in access logs, browser history and `Referer`
 * headers.
 */
const registrationTeamService = {
  /** The public roster of registered teams. Invites are omitted server-side. */
  async listPublic(tournamentId: number): Promise<RegistrationTeamListResponse> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration-teams`);
    return response.json();
  },

  /** Organizer view: includes invites, and optionally terminal teams. */
  async listAdmin(
    tournamentId: number,
    options?: { includeTerminal?: boolean },
  ): Promise<RegistrationTeamListResponse> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams`,
      { query: options?.includeTerminal ? { include_terminal: "true" } : undefined },
    );
    return response.json();
  },

  async create(tournamentId: number, input: RegistrationTeamCreateInput): Promise<RegistrationTeam> {
    const response = await apiFetch(`/api/v1/tournaments/${tournamentId}/registration-teams`, {
      method: "POST",
      body: input,
    });
    return response.json();
  },

  /**
   * Set the team's logo. Captain-only, enforced server-side.
   *
   * Deliberately a SECOND call after `create` rather than a field on its payload:
   * `create_team` runs one transaction that must also write the captain's
   * registration, and an S3 round trip inside it would either lengthen that lock
   * or, on failure, roll back a team the captain already named. A failed logo
   * upload must leave the team standing.
   */
  async uploadImage(teamId: number, file: File): Promise<RegistrationTeam> {
    const formData = new FormData();
    formData.append("file", file);
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}/image`, {
      method: "POST",
      body: formData,
    });
    return response.json();
  },

  async deleteImage(teamId: number): Promise<RegistrationTeam> {
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}/image`, {
      method: "DELETE",
    });
    return response.json();
  },

  /** Returns the invite plus, for a link invite, the raw token — shown ONCE. */
  async invite(
    teamId: number,
    input: RegistrationTeamInviteInput,
  ): Promise<RegistrationTeamInviteCreated> {
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}/invites`, {
      method: "POST",
      body: input,
    });
    return response.json();
  },

  async revokeInvite(inviteId: number): Promise<void> {
    await apiFetch(`/api/v1/registration-teams/invites/${inviteId}`, { method: "DELETE" });
  },

  async accept(input: RegistrationTeamAcceptInput): Promise<RegistrationTeam> {
    const response = await apiFetch(`/api/v1/registration-teams/invites/accept`, {
      method: "POST",
      body: input,
    });
    return response.json();
  },

  async decline(input: { token?: string; invite_id?: number }): Promise<void> {
    await apiFetch(`/api/v1/registration-teams/invites/decline`, { method: "POST", body: input });
  },

  async kick(teamId: number, registrationId: number): Promise<void> {
    await apiFetch(`/api/v1/registration-teams/${teamId}/members/${registrationId}`, {
      method: "DELETE",
    });
  },

  async leave(teamId: number): Promise<void> {
    await apiFetch(`/api/v1/registration-teams/${teamId}/members/me`, { method: "DELETE" });
  },

  async transferCaptaincy(teamId: number, registrationId: number): Promise<void> {
    await apiFetch(`/api/v1/registration-teams/${teamId}/captain/${registrationId}`, {
      method: "POST",
    });
  },

  async disband(teamId: number): Promise<void> {
    await apiFetch(`/api/v1/registration-teams/${teamId}`, { method: "DELETE" });
  },

  /** Reject the team without withdrawing players unless explicitly requested. */
  async reject(
    tournamentId: number,
    teamId: number,
    options: { withdrawMembers?: boolean; reason: string },
  ): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}/reject`,
      {
        method: "POST",
        body: {
          withdraw_members: options.withdrawMembers ?? false,
          reason: options.reason,
        },
      },
    );
    return response.json();
  },

  /** Materialize complete teams into `tournament.team`. Refuses when standings
   *  already exist for teams it does not own, so it cannot invalidate a bracket. */
  async exportRegistered(
    tournamentId: number,
    teamIds?: number[],
  ): Promise<RegistrationTeamExportResult> {
    const response = await apiFetch(
      `/api/balancer/tournaments/${tournamentId}/registered-teams/export`,
      { method: "POST", body: teamIds !== undefined ? { team_ids: teamIds } : {} },
    );
    return response.json();
  },

  /** Who the captain may invite: this tournament's registrants on no team. */
  async listFreeAgents(tournamentId: number): Promise<RegistrationFreeAgentListResponse> {
    const response = await apiFetch(
      `/api/v1/tournaments/${tournamentId}/registration-teams/free-agents`,
    );
    return response.json();
  },

  /**
   * Invites addressed to the current user.
   *
   * Scoped server-side from the caller's token — there is no id to pass, because
   * "whose invites" is never the client's answer.
   */
  async listMyInvites(tournamentId: number): Promise<RegistrationTeamInviteOfferListResponse> {
    const response = await apiFetch(
      `/api/v1/tournaments/${tournamentId}/registration-teams/my-invites`,
    );
    return response.json();
  },

  /**
   * A captain's own team's full invite history, plus its cap standing.
   *
   * Captaincy-gated in the worker; the organizer reads the same rows through
   * `listInviteHistoryAdmin`. Deliberately NOT folded into the team read: that one
   * returns only live invites because occupancy depends on them reserving slots.
   */
  async listInviteHistory(teamId: number): Promise<RegistrationTeamInviteHistoryResponse> {
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}/invite-history`);
    return response.json();
  },

  /** The same history for an organizer, authorized against the tournament. */
  async listInviteHistoryAdmin(
    tournamentId: number,
    teamId: number,
  ): Promise<RegistrationTeamInviteHistoryResponse> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}/invite-history`,
    );
    return response.json();
  },

  /**
   * An organizer withdraws an offer from a team they do not captain.
   *
   * The tournament is in the path because that is what the permission is checked
   * against — an invite id is global while the permission is not.
   */
  async revokeInviteAdmin(tournamentId: number, inviteId: number): Promise<void> {
    await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/invites/${inviteId}`,
      { method: "DELETE" },
    );
  },

  /**
   * Forgive a team's cumulative invite count.
   *
   * The recourse the cap's own error message names. Before this existed it named
   * an intervention no endpoint provided.
   */
  async resetInviteCap(tournamentId: number, teamId: number): Promise<void> {
    await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}/invite-cap/reset`,
      { method: "POST" },
    );
  },

  async rename(teamId: number, name: string): Promise<RegistrationTeam> {
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}`, {
      method: "PATCH",
      body: { name },
    });
    return response.json();
  },

  async placeMember(
    teamId: number,
    registrationId: number,
    input: { slot_code: string; is_substitute?: boolean; swap_with_registration_id?: number | null },
  ): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/registration-teams/${teamId}/members/${registrationId}/place`,
      { method: "POST", body: input },
    );
    return response.json();
  },

  async setManager(teamId: number, registrationId: number, isManager: boolean): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/registration-teams/${teamId}/members/${registrationId}/manager`,
      { method: "POST", body: { is_manager: isManager } },
    );
    return response.json();
  },

  async extendInvite(
    teamId: number,
    inviteId: number,
    input?: { ttl_days?: number | null; rotate_token?: boolean },
  ): Promise<RegistrationTeamInviteCreated> {
    const response = await apiFetch(
      `/api/v1/registration-teams/${teamId}/invites/${inviteId}/extend`,
      { method: "POST", body: input ?? {} },
    );
    return response.json();
  },

  async lockRoster(teamId: number): Promise<RegistrationTeam> {
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}/lock`, { method: "POST" });
    return response.json();
  },

  async checkInRoster(teamId: number, excludeRegistrationIds: number[] = []): Promise<RegistrationTeam> {
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}/check-in`, {
      method: "POST",
      body: { exclude_registration_ids: excludeRegistrationIds },
    });
    return response.json();
  },

  async coverSubscription(
    teamId: number,
    input?: { code?: string | null; provider?: string },
  ): Promise<RegistrationTeam> {
    const response = await apiFetch(`/api/v1/registration-teams/${teamId}/subscription/cover`, {
      method: "POST",
      body: input ?? {},
    });
    return response.json();
  },

  async renameAdmin(tournamentId: number, teamId: number, name: string): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}`,
      { method: "PATCH", body: { name } },
    );
    return response.json();
  },

  async unlockRoster(tournamentId: number, teamId: number): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}/unlock`,
      { method: "POST" },
    );
    return response.json();
  },

  async setAdmission(
    tournamentId: number,
    teamId: number,
    admission: "pending" | "accepted" | "waitlisted",
  ): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}/admission`,
      { method: "POST", body: { admission } },
    );
    return response.json();
  },

  async setNotes(tournamentId: number, teamId: number, notes: string | null): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}/notes`,
      { method: "POST", body: { notes } },
    );
    return response.json();
  },

  async placeMemberAdmin(
    tournamentId: number,
    teamId: number,
    registrationId: number,
    input: { slot_code: string; is_substitute?: boolean },
  ): Promise<RegistrationTeam> {
    const response = await apiFetch(
      `/api/v1/admin/balancer/tournaments/${tournamentId}/registration-teams/${teamId}/members/${registrationId}/place`,
      { method: "POST", body: input },
    );
    return response.json();
  },

  /**
   * Resolve a shared invite link. The only anonymous call in this service.
   *
   * POST for a read on purpose: the token must not land in a query string, where
   * it would be logged by every hop. It reaches the server in the body, and the
   * link itself keeps it in the URL fragment, which no browser transmits at all.
   */
  async previewInvite(token: string): Promise<RegistrationTeamInvitePreview> {
    const response = await apiFetch("/api/v1/registration-teams/invites/preview", {
      method: "POST",
      body: { token },
      // Neither is known on the landing page, and neither is needed: the token is
      // the whole credential and the invite names its own tournament.
      skipAuth: true,
      skipWorkspace: true,
    });
    return response.json();
  },
};

export default registrationTeamService;
