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
  source_workspace_id: number | null;
  source_grid_id: number | null;
  source_key: string | null;
  source_fingerprint: string | null;
  imported_at: string | null;
  archived_at: string | null;
}

export interface DivisionGridMappingRule {
  id?: number;
  mapping_id?: number;
  source_tier_id: number;
  target_tier_id: number;
  weight: number;
  is_primary: boolean;
}

export interface DivisionGridMarketplaceWorkspace {
  id: number;
  slug: string;
  name: string;
  grids_count: number;
  versions_count: number;
}

interface DivisionGridMarketplaceVersion {
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
  source_grid_id: number;
  source_version_id: number;
  include_icons: boolean;
  include_ow_rank_mappings: boolean;
}

interface DivisionGridMarketplaceImportedGrid {
  source_grid_id: number;
  target_grid_id: number;
  slug: string;
  name: string;
  versions_count: number;
  tiers_count: number;
}

interface DivisionGridMarketplaceImportWarning {
  grid_slug?: string | null;
  message: string;
}

interface DivisionGridMarketplaceImportResult {
  created_grids: number;
  created_versions: number;
  created_tiers: number;
  copied_images: number;
  copied_mappings: number;
  imported_grids: DivisionGridMarketplaceImportedGrid[];
  warnings: DivisionGridMarketplaceImportWarning[];
}

export interface DivisionGridMarketplacePreflightResult {
  source_workspace_id: number;
  grids_count: number;
  versions_count: number;
  tiers_count: number;
  mappings_count: number;
  assets_to_copy: number;
  assets_to_reuse: number;
  external_assets: number;
  conflicts: string[];
  warnings: DivisionGridMarketplaceImportWarning[];
  source_fingerprint: string;
}

export interface DivisionGridImportJob {
  id: number;
  workspace_id: number;
  requested_by_user_id: number | null;
  source_workspace_id: number | null;
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  result: DivisionGridMarketplaceImportResult | null;
  error: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

interface DivisionGridReadinessConflictTier {
  source_tier_id: number;
  slug: string;
  name: string;
}

export interface DivisionGridReadinessSource {
  version_id: number;
  version_label: string;
  grid_name: string;
  tournament_count: number;
  tournament_names: string[];
  status: "ok" | "missing" | "incomplete";
  conflict_tiers: DivisionGridReadinessConflictTier[];
}

export interface DivisionGridActivationReadiness {
  target_version_id: number;
  is_ready: boolean;
  used_source_version_ids: number[];
  missing_mapping_version_ids: number[];
  incomplete_mapping_version_ids: number[];
  sources: DivisionGridReadinessSource[];
}

export interface DivisionGridSaveResult {
  mode: "in_place" | "new_version_activated" | "new_version_pending";
  grid: DivisionGridEntity;
  active_version_id: number | null;
  saved_version_id: number;
  readiness: DivisionGridActivationReadiness;
}

interface DivisionGridPortableMappingRule {
  source_tier_slug: string;
  target_tier_slug: string;
  weight: number;
  is_primary: boolean;
}

interface DivisionGridPortableMapping {
  source_version: number;
  target_version: number;
  name: string;
  rules: DivisionGridPortableMappingRule[];
}

export interface DivisionGridPortableDocument {
  schema_version: "division-grid/v1";
  slug: string;
  name: string;
  description: string | null;
  versions: Array<{
    version: number;
    label: string;
    status: "draft" | "published";
    tiers: DivisionTier[];
  }>;
  mappings: DivisionGridPortableMapping[];
}

/** Trust tier of a workspace. New self-service workspaces start `unverified`
 * and stay off the public home-page directory until a superuser reviews them;
 * the directory lists `verified` and `trusted`, and badges the latter. */
export type WorkspaceVerificationStatus = "unverified" | "verified" | "trusted";

/** `scope` of `GET /api/v1/workspaces`. `public` is the shared home-page
 * directory (no hidden, no `unverified` — identical for superusers), `admin`
 * the management list, `all` the switcher's union of both. */
export type WorkspaceListScope = "public" | "admin" | "all";

/** A Discord guild the signed-in user administers, from `GET /api/v1/me/discord-guilds`. */
export interface ManageableDiscordGuild {
  guild_id: string;
  name: string;
  icon_url?: string | null;
  owner: boolean;
  can_manage: boolean;
}

export interface Workspace {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  icon_url: string | null;
  is_active: boolean;
  /** Excludes this workspace from the anonymous/non-member `/api/v1/workspaces`
   * list (home page, other members' workspace picker). A member still sees
   * it; direct access by slug/subdomain/custom domain is unaffected. */
  is_hidden: boolean;
  /** IANA zone tournament schedule forms display and parse times in. */
  timezone: string;
  /** Per-workspace main-site branding (see lib/workspace-theme). */
  branding_enabled: boolean;
  brand_primary: string | null;
  brand_secondary: string | null;
  brand_background: string | null;
  brand_surface: string | null;
  brand_accent: string | null;
  brand_foreground: string | null;
  brand_muted: string | null;
  brand_border: string | null;
  brand_ring: string | null;
  brand_destructive: string | null;
  subdomain: string | null;
  seo_title: string | null;
  seo_description: string | null;
  /** White-label custom domain (Phase 2). Resolver serves it only once verified. */
  custom_domain: string | null;
  custom_domain_verified_at: string | null;
  /** Required value of the `_owt-verify.<custom_domain>` TXT record; not secret. */
  custom_domain_verification_token: string | null;
  /** The one Discord guild this workspace runs in — Boosty patron roles and match-log channels alike. */
  discord_guild_id: string | null;
  /** Set when an administrator of that guild proved it through Discord OAuth. */
  discord_guild_verified_at: string | null;
  /** Self-service trust tier: `unverified` workspaces are absent from the
   * public directory (`scope=public`) for every caller, superusers included. */
  verification_status: WorkspaceVerificationStatus;
  default_division_grid_version_id: number | null;
  default_division_grid_version: DivisionGridVersion | null;
  /** How "is this player new" is decided when a roster is created: `"global"`
   * counts any workspace's tournaments, `"workspace"` counts only this
   * workspace's. */
  newcomer_scope: "global" | "workspace";
}

/**
 * `Workspace.owner_id` resolved to a person — the account accountable for the
 * workspace (and counted against the per-account create cap).
 *
 * Not a field on `Workspace`: that model comes from the anonymous, edge-cached
 * `/api/v1/workspaces` reads, so the owner lives behind its own
 * `workspace.update`-gated endpoint. `null` from the API means no owner is
 * stamped at all (every workspace predating self-service creation).
 */
export interface WorkspaceOwner {
  auth_user_id: number;
  username: string | null;
  email: string | null;
  first_name: string | null;
  last_name: string | null;
  avatar_url: string | null;
}

/**
 * Organiser-controlled branding: 4 seed colours (primary/secondary/background/
 * surface) that derive the full palette, plus 6 optional core-palette overrides
 * (accent/foreground/muted/border/ring/destructive) that win when set.
 */
export interface WorkspaceBranding {
  branding_enabled: boolean;
  brand_primary: string | null;
  brand_secondary: string | null;
  brand_background: string | null;
  brand_surface: string | null;
  brand_accent?: string | null;
  brand_foreground?: string | null;
  brand_muted?: string | null;
  brand_border?: string | null;
  brand_ring?: string | null;
  brand_destructive?: string | null;
}

export type WorkspaceSystemRole = "owner" | "admin" | "host" | "member" | "player";

export interface WorkspaceMember {
  id: number;
  workspace_id: number;
  auth_user_id: number;
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
