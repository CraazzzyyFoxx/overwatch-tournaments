import { apiFetch } from "@/lib/api-fetch";
import type { PaginatedResponse } from "@/types/pagination.types";
import {
  DivisionGridEntity,
  DivisionGridMarketplaceGrid,
  DivisionGridMarketplaceImportRequest,
  DivisionGridMarketplaceImportResult,
  DivisionGridMarketplaceWorkspace,
  DivisionGridMappingRule,
  DivisionGridVersion,
  Workspace,
  WorkspaceMember
} from "@/types/workspace.types";

export default class workspaceService {
  static async getAll(): Promise<Workspace[]> {
    return apiFetch("/api/v1/workspaces").then((r) => r.json());
  }

  static async getById(id: number): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${id}`).then((r) => r.json());
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
      branding_enabled?: boolean;
      brand_primary?: string | null;
      brand_secondary?: string | null;
      brand_background?: string | null;
      brand_surface?: string | null;
      default_division_grid_version_id?: number | null;
    }
  ): Promise<Workspace> {
    return apiFetch(`/api/v1/workspaces/${id}`, {
      method: "PATCH",
      body: data
    }).then((r) => r.json());
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

  static async getDivisionGridVersions(
    _workspaceId: number,
    gridId: number
  ): Promise<DivisionGridVersion[]> {
    return apiFetch(`/api/v1/division-grids/${gridId}/versions`).then((r) => r.json());
  }

  static async createDivisionGridVersion(
    _workspaceId: number,
    gridId: number,
    data: {
      label: string;
      tiers: Array<{
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
      tiers?: Array<{
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
    return apiFetch(`/api/v1/division-grids/mappings/${sourceVersionId}/${targetVersionId}`
    ).then((r) => r.json());
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
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/marketplace/workspaces`
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

  static async importDivisionGridMarketplace(
    workspaceId: number,
    data: DivisionGridMarketplaceImportRequest
  ): Promise<DivisionGridMarketplaceImportResult> {
    return apiFetch(`/api/v1/division-grids/by-workspace/${workspaceId}/marketplace/import`, {
      method: "POST",
      body: data
    }).then((r) => r.json());
  }
}
