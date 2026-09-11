import { apiFetch } from "@/lib/api-fetch";
import type { PaginatedResponse } from "@/types/pagination.types";
import {
  DivisionGridActivationReadiness,
  DivisionGridEntity,
  DivisionGridImportJob,
  DivisionGridMarketplaceGrid,
  DivisionGridMarketplaceImportRequest,
  DivisionGridMarketplacePreflightResult,
  DivisionGridMarketplaceWorkspace,
  DivisionGridMappingRule,
  DivisionGridPortableDocument,
  DivisionGridSaveResult,
  DivisionGridVersion,
  ManageableDiscordGuild,
  Workspace,
  WorkspaceListScope,
  WorkspaceMember,
  WorkspaceOwner,
  WorkspaceVerificationStatus
} from "@/types/workspace.types";
import type {
  DiscordChannelsResponse,
  DiscordGuildInfo,
  DiscordRolesResponse
} from "@/types/discord.types";

type DivisionGridTierInput = {
  id?: number;
  slug: string;
  number: number;
  name: string;
  sort_order: number;
  rank_min: number;
  rank_max: number | null;
  icon_url: string;
  ow_rank_min: number | null;
  ow_rank_max: number | null;
};
export default class workspaceService {
  /**
   * `public` (default) is the home-page directory: hidden and `unverified`
   * workspaces are absent for everyone, superusers included. `admin` is the
   * management list (superuser: everything, else own memberships) and `all`
   * unions that with the directory, for the switcher and slug resolution.
   */
  static async getAll(scope: WorkspaceListScope = "public"): Promise<Workspace[]> {
    return apiFetch("/api/v1/workspaces", { query: { scope } }).then((r) => r.json());
  }

  static async getById(id: number): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${id}`).then((r) => r.json());
  }

  /**
   * The account accountable for a workspace, or `null` when none is stamped.
   * Requires `workspace.update` — `getById` is public and carries no owner.
   */
  static async getOwner(id: number): Promise<WorkspaceOwner | null> {
    return apiFetch(`/api/v1/workspaces/${id}/owner`).then((r) => r.json());
  }

  /**
   * Stamp or clear the accountable owner. Superuser-only server-side — the cap
   * on how many workspaces an account may own is counted over this field.
   */
  static async setOwner(id: number, authUserId: number | null): Promise<WorkspaceOwner | null> {
    return apiFetch(`/api/v1/workspaces/${id}/owner`, {
      method: "PUT",
      body: { auth_user_id: authUserId }
    }).then((r) => r.json());
  }

  /**
   * Hand the workspace over: the accountability stamp AND the RBAC `owner`
   * role. Allowed for the current owner as well as superusers, unlike
   * `setOwner`, which only moves the stamp.
   */
  static async transferOwnership(id: number, authUserId: number): Promise<WorkspaceOwner> {
    return apiFetch(`/api/v1/workspaces/${id}/owner/transfer`, {
      method: "POST",
      body: { auth_user_id: authUserId }
    }).then((r) => r.json());
  }

  static async create(data: {
    slug: string;
    name: string;
    description?: string;
    icon_url?: string;
  }): Promise<Workspace> {
    return apiFetch("/api/v1/workspaces", {
      method: "POST",
      body: data
    }).then((r) => r.json());
  }

  static async update(
    id: number,
    data: {
      name?: string;
      description?: string;
      icon_url?: string | null;
      is_active?: boolean;
      is_hidden?: boolean;
      branding_enabled?: boolean;
      brand_primary?: string | null;
      brand_secondary?: string | null;
      brand_background?: string | null;
      brand_surface?: string | null;
      brand_accent?: string | null;
      brand_foreground?: string | null;
      brand_muted?: string | null;
      brand_border?: string | null;
      brand_ring?: string | null;
      brand_destructive?: string | null;
      subdomain?: string | null;
      seo_title?: string | null;
      seo_description?: string | null;
      newcomer_scope?: "global" | "workspace";
      default_division_grid_version_id?: number | null;
    }
  ): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${id}`, {
      method: "PATCH",
      body: data
    }).then((r) => r.json());
  }

  static async delete(id: number): Promise<void> {
    await apiFetch(`/api/v1/workspaces/${id}`, { method: "DELETE" });
  }

  static async getMembers(
    workspaceId: number,
    params?: {
      page?: number;
      per_page?: number;
      search?: string;
      role_id?: number | null;
      sort?: "username" | "role";
      order?: "asc" | "desc";
    }
  ): Promise<PaginatedResponse<WorkspaceMember>> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/members`, {
      query: {
        page: params?.page,
        per_page: params?.per_page,
        search: params?.search?.trim() || undefined,
        role_id: params?.role_id ?? undefined,
        sort: params?.sort,
        order: params?.order
      }
    }).then((r) => r.json());
  }

  /** Fetch every member (for selectors, not the paginated table). */
  static async getMembersAll(workspaceId: number): Promise<WorkspaceMember[]> {
    const page = await this.getMembers(workspaceId, { per_page: -1 });
    return page.results;
  }

  /** Grant the baseline "member" role to every member currently without a role. */
  static async autofillMemberRoles(workspaceId: number): Promise<{ assigned: number }> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/members/autofill-roles`, {
      method: "POST"
    }).then((r) => r.json());
  }

  static async addMember(
    workspaceId: number,
    authUserId: number,
    roleIds?: number[]
  ): Promise<WorkspaceMember> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/members`, {
      method: "POST",
      body: { auth_user_id: authUserId, role_ids: roleIds }
    }).then((r) => r.json());
  }

  static async updateMemberRole(
    workspaceId: number,
    authUserId: number,
    roleIds: number[]
  ): Promise<WorkspaceMember> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/members/${authUserId}`, {
      method: "PATCH",
      body: { role_ids: roleIds }
    }).then((r) => r.json());
  }

  static async removeMember(workspaceId: number, authUserId: number): Promise<void> {
    await apiFetch(`/api/v1/workspaces/${workspaceId}/members/${authUserId}`, {
      method: "DELETE"
    });
  }

  /** Store a normalized custom domain + a fresh DNS TXT verification token (unverified). */
  static async setCustomDomain(workspaceId: number, customDomain: string): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/custom-domain`, {
      method: "POST",
      body: { custom_domain: customDomain }
    }).then((r) => r.json());
  }

  /** Check the `_owt-verify.<domain>` DNS TXT record against the stored token. */
  static async verifyCustomDomain(workspaceId: number): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/custom-domain/verify`, {
      method: "POST"
    }).then((r) => r.json());
  }

  /** Remove the custom domain, its token, and its verification state. */
  static async clearCustomDomain(workspaceId: number): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/custom-domain`, {
      method: "DELETE"
    }).then((r) => r.json());
  }

  /** Every Discord guild the signed-in user administers (owner or MANAGE_GUILD). */
  static async myDiscordGuilds(): Promise<ManageableDiscordGuild[]> {
    return apiFetch("/api/v1/me/discord-guilds")
      .then((r) => r.json())
      .then((body: { guilds?: ManageableDiscordGuild[] }) => body.guilds ?? []);
  }

  /**
   * Bind a Discord guild to a workspace, proving the caller administers it.
   *
   * The guild is no longer a PATCH-able field: the backend re-asks Discord who
   * administers it on every bind, so 403 (not yours any more), 409 (another
   * workspace claimed it) and 503 (Discord unreachable) are all real answers a
   * plain form field could not have produced.
   */
  static async verifyDiscordGuild(workspaceId: number, guildId: string): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/discord-guild`, {
      method: "POST",
      body: { guild_id: guildId }
    }).then((r) => r.json());
  }

  /** Drop the Discord guild claim. Workspace.update is enough — Discord is not re-asked. */
  static async clearDiscordGuild(workspaceId: number): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/discord-guild`, {
      method: "DELETE"
    }).then((r) => r.json());
  }

  /** Superuser-only trust tier change (`unverified` | `verified` | `trusted`). */
  static async setVerificationStatus(
    workspaceId: number,
    status: WorkspaceVerificationStatus
  ): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/verification`, {
      method: "POST",
      body: { verification_status: status }
    }).then((r) => r.json());
  }

  static async uploadIcon(workspaceId: number, file: File): Promise<Workspace> {
    const formData = new FormData();
    formData.append("file", file);
    return apiFetch(`/api/v1/workspaces/${workspaceId}/icon`, {
      method: "POST",
      body: formData
    }).then((r) => r.json());
  }

  static async deleteIcon(workspaceId: number): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/icon`, {
      method: "DELETE"
    }).then((r) => r.json());
  }

  static async getDivisionGrids(workspaceId: number): Promise<DivisionGridEntity[]> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}`).then((r) => r.json());
  }

  static async createDivisionGrid(
    workspaceId: number,
    data: { slug: string; name: string; description?: string | null }
  ): Promise<DivisionGridEntity> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}`, {
      method: "POST",
      body: data
    }).then((r) => r.json());
  }

  static async updateDivisionGrid(
    gridId: number,
    data: { name?: string; description?: string | null; archived?: boolean }
  ): Promise<DivisionGridEntity> {
    return apiFetch(`/api/v1/division-grids/library/${gridId}`, {
      method: "PATCH",
      body: data
    }).then((r) => r.json());
  }

  static async deleteDivisionGrid(gridId: number, force = false): Promise<void> {
    await apiFetch(`/api/v1/division-grids/library/${gridId}`, {
      method: "DELETE",
      query: force ? { force: true } : undefined
    });
  }

  static async saveWorkspaceGrid(
    workspaceId: number,
    data: {
      grid_id?: number | null;
      name?: string | null;
      tiers: Array<{
        id?: number | null;
        slug: string;
        number: number;
        name: string;
        sort_order: number;
        rank_min: number;
        rank_max: number | null;
        icon_url: string;
        ow_rank_min: number | null;
        ow_rank_max: number | null;
      }>;
    }
  ): Promise<DivisionGridSaveResult> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/grid`, {
      method: "PUT",
      body: data
    }).then((r) => r.json());
  }

  static async getDivisionGridVersions(
    _workspaceId: number,
    gridId: number
  ): Promise<DivisionGridVersion[]> {
    return apiFetch(`/api/v1/division-grids/${gridId}/versions`).then((r) => r.json());
  }
  static async getDivisionGridVersion(versionId: number): Promise<DivisionGridVersion> {
    return apiFetch(`/api/v1/division-grids/versions/${versionId}`).then((r) => r.json());
  }

  static async createDivisionGridVersion(
    _workspaceId: number,
    gridId: number,
    data: {
      label: string;
      tiers: DivisionGridTierInput[];
    }
  ): Promise<DivisionGridVersion> {
    return apiFetch(`/api/v1/division-grids/${gridId}/versions`, {
      method: "POST",
      body: data
    }).then((r) => r.json());
  }

  static async publishDivisionGridVersion(versionId: number): Promise<DivisionGridVersion> {
    return apiFetch(`/api/v1/division-grids/versions/${versionId}/publish`, {
      method: "POST",
      body: {}
    }).then((r) => r.json());
  }

  static async getDivisionGridVersionReadiness(
    workspaceId: number,
    versionId: number
  ): Promise<DivisionGridActivationReadiness> {
    return apiFetch(
      `/api/v1/division-grids/by-workspace/${workspaceId}/versions/${versionId}/readiness`
    ).then((r) => r.json());
  }

  static async activateDivisionGridVersion(
    workspaceId: number,
    versionId: number
  ): Promise<DivisionGridVersion> {
    return apiFetch(
      `/api/v1/division-grids/by-workspace/${workspaceId}/versions/${versionId}/activate`,
      { method: "POST", body: {} }
    ).then((r) => r.json());
  }

  static async cloneDivisionGridVersion(versionId: number): Promise<DivisionGridVersion> {
    return apiFetch(`/api/v1/division-grids/versions/${versionId}/clone`, {
      method: "POST",
      body: {}
    }).then((r) => r.json());
  }

  static async deleteDivisionGridVersion(versionId: number): Promise<void> {
    await apiFetch(`/api/v1/division-grids/versions/${versionId}`, { method: "DELETE" });
  }

  static async updateDivisionGridVersion(
    versionId: number,
    data: {
      label?: string;
      tiers?: DivisionGridTierInput[];
    }
  ): Promise<DivisionGridVersion> {
    return apiFetch(`/api/v1/division-grids/versions/${versionId}`, {
      method: "PATCH",
      body: data
    }).then((r) => r.json());
  }

  static async uploadDivisionIcon(
    slug: string,
    file: File,
    workspaceId: number
  ): Promise<{ key: string; public_url: string }> {
    const formData = new FormData();
    formData.append("file", file);
    return apiFetch(`/api/v1/assets/divisions/${slug}`, {
      method: "POST",
      body: formData,
      query: { workspace_id: workspaceId }
    }).then((r) => r.json());
  }

  static async getDivisionGridMapping(
    sourceVersionId: number,
    targetVersionId: number
  ): Promise<{
    id: number;
    source_version_id: number;
    target_version_id: number;
    name: string;
    is_complete: boolean;
    rules: DivisionGridMappingRule[];
  }> {
    return apiFetch(`/api/v1/division-grids/mappings/${sourceVersionId}/${targetVersionId}`).then(
      (r) => r.json()
    );
  }

  static async putDivisionGridMapping(
    sourceVersionId: number,
    targetVersionId: number,
    data: { name: string; rules: DivisionGridMappingRule[] }
  ): Promise<{
    id: number;
    source_version_id: number;
    target_version_id: number;
    name: string;
    is_complete: boolean;
    rules: DivisionGridMappingRule[];
  }> {
    return apiFetch(`/api/v1/division-grids/mappings/${sourceVersionId}/${targetVersionId}`, {
      method: "PUT",
      body: data
    }).then((r) => r.json());
  }

  static async getDivisionGridMarketplaceWorkspaces(
    workspaceId: number
  ): Promise<DivisionGridMarketplaceWorkspace[]> {
    return apiFetch(
      `/api/v1/division-grids/by-workspace/${workspaceId}/marketplace/workspaces`
    ).then((r) => r.json());
  }

  static async getDivisionGridMarketplace(
    workspaceId: number,
    sourceWorkspaceId: number
  ): Promise<DivisionGridMarketplaceGrid[]> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/marketplace`, {
      query: { source_workspace_id: sourceWorkspaceId }
    }).then((r) => r.json());
  }

  static async preflightDivisionGridMarketplace(
    workspaceId: number,
    data: DivisionGridMarketplaceImportRequest
  ): Promise<DivisionGridMarketplacePreflightResult> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/marketplace/preflight`, {
      method: "POST",
      body: data
    }).then((r) => r.json());
  }

  static async importDivisionGridMarketplace(
    workspaceId: number,
    data: DivisionGridMarketplaceImportRequest
  ): Promise<DivisionGridImportJob> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/marketplace/import`, {
      method: "POST",
      body: data
    }).then((r) => r.json());
  }

  static async getDivisionGridImportJobs(
    workspaceId: number,
    activeOnly = false,
    limit = 20
  ): Promise<DivisionGridImportJob[]> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/import-jobs`, {
      query: { active_only: activeOnly, limit }
    }).then((r) => r.json());
  }

  static async getDivisionGridImportJob(
    workspaceId: number,
    jobId: number
  ): Promise<DivisionGridImportJob> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/import-jobs/${jobId}`).then(
      (r) => r.json()
    );
  }

  static async exportDivisionGridPortable(gridId: number): Promise<DivisionGridPortableDocument> {
    return apiFetch(`/api/v1/division-grids/library/${gridId}/export`).then((r) => r.json());
  }

  static async importDivisionGridPortable(
    workspaceId: number,
    document: DivisionGridPortableDocument,
    mode: "library" | "sync" | "copy" = "library"
  ): Promise<DivisionGridEntity> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/portable/import`, {
      method: "POST",
      body: { document, mode }
    }).then((r) => r.json());
  }
  static async getDiscordRoles(workspaceId: number): Promise<DiscordRolesResponse> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/discord/roles`).then((r) => r.json());
  }

  static async getDiscordChannels(workspaceId: number): Promise<DiscordChannelsResponse> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/discord/channels`).then((r) => r.json());
  }

  static async getDiscordGuildInfo(workspaceId: number): Promise<DiscordGuildInfo> {
    return apiFetch(`/api/v1/workspaces/${workspaceId}/discord/guild`).then((r) => r.json());
  }
}
