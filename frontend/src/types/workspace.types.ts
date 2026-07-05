export interface DivisionTier {
  id?: number;
  slug?: string;
  number: number;
  name: string;
  rank_min: number;
  rank_max: number | null;
  sort_order?: number;
  icon_url: string;
  ow_rank_min?: number | null;
  ow_rank_max?: number | null;
}

export interface DivisionGrid {
  tiers: DivisionTier[];
}

export interface DivisionGridVersion {
  id: number;
  grid_id: number;
  version: number;
  label: string;
  status: "draft" | "published" | "archived" | string;
  created_from_version_id: number | null;
  published_at: string | null;
  tiers: DivisionTier[];
}

export interface DivisionGridEntity {
  id: number;
  workspace_id: number | null;
  slug: string;
  name: string;
  description: string | null;
  versions: DivisionGridVersion[];
}

export interface DivisionGridMappingRule {
  id?: number;
  mapping_id?: number;
  source_tier_id: number;
  target_tier_id: number;
  weight: number;
  is_primary: boolean;
}

export interface DivisionGridMapping {
  id: number;
  source_version_id: number;
  target_version_id: number;
  name: string;
  is_complete: boolean;
  rules: DivisionGridMappingRule[];
}

export interface DivisionGridMarketplaceWorkspace {
  id: number;
  slug: string;
  name: string;
  grids_count: number;
  versions_count: number;
}

export interface DivisionGridMarketplaceVersion {
  id: number;
  version: number;
  label: string;
  status: string;
  tiers_count: number;
  preview_icon_urls: string[];
}

export interface DivisionGridMarketplaceGrid {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  versions_count: number;
  tiers_count: number;
  preview_icon_urls: string[];
  versions: DivisionGridMarketplaceVersion[];
}

export interface DivisionGridMarketplaceImportRequest {
  source_workspace_id: number;
  source_grid_ids: number[];
  set_default?: boolean;
}

export interface DivisionGridMarketplaceImportedGrid {
  source_grid_id: number;
  target_grid_id: number;
  slug: string;
  name: string;
  versions_count: number;
  tiers_count: number;
}

export interface DivisionGridMarketplaceImportWarning {
  grid_slug?: string | null;
  message: string;
}

export interface DivisionGridMarketplaceImportResult {
  created_grids: number;
  created_versions: number;
  created_tiers: number;
  copied_images: number;
  copied_mappings: number;
  imported_grids: DivisionGridMarketplaceImportedGrid[];
  warnings: DivisionGridMarketplaceImportWarning[];
}

export interface Workspace {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  icon_url: string | null;
  is_active: boolean;
  default_division_grid_version_id: number | null;
  default_division_grid_version: DivisionGridVersion | null;
}

export type WorkspaceSystemRole = "owner" | "admin" | "member" | "player";

export interface WorkspaceMember {
  id: number;
  workspace_id: number;
  auth_user_id: number;
  /** Highest system role held (owner > admin > member > player). */
  role: WorkspaceSystemRole;
  username?: string | null;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
  avatar_url?: string | null;
  rbac_roles: Array<{
    id: number;
    name: string;
    description?: string | null;
    is_system: boolean;
    workspace_id?: number | null;
  }>;
}

export interface WorkspaceMembership {
  workspace_id: number;
  slug: string;
  role: string;
  rbac_roles: string[];
  rbac_permissions: string[];
}
