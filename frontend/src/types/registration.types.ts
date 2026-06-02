import type { DivisionGridVersion } from "@/types/workspace.types";

export interface CustomFieldDefinition {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "checkbox" | "url";
  required: boolean;
  placeholder: string | null;
  options: string[] | null;
  validation?: FieldValidationConfig | null;
}

export interface FieldValidationConfig {
  regex?: string | null;
  error_message?: string | null;
}

export interface BuiltInFieldConfig {
  enabled: boolean;
  required: boolean;
  subroles?: Record<string, string[]>;
  validation?: FieldValidationConfig | null;
  /** `top_heroes` field only: max heroes selectable per role (default 5). */
  max_heroes?: number | null;
}

export interface SubroleOption {
  slug: string;
  label: string;
}

/** Workspace sub-role catalog keyed by registration role code (tank/dps/support). */
export type SubroleCatalog = Record<string, SubroleOption[]>;

export interface RegistrationForm {
  id: number;
  tournament_id: number;
  workspace_id: number;
  is_open: boolean;
  opens_at: string | null;
  closes_at: string | null;
  require_open_profile?: boolean;
  open_profile_scope?: "main" | "all";
  built_in_fields: Record<string, BuiltInFieldConfig>;
  custom_fields: CustomFieldDefinition[];
  subrole_catalog?: SubroleCatalog;
}

export type RegistrationStatus = string;

export type BalancerStatus = string;

export interface StatusMeta {
  value: string;
  scope: "registration" | "balancer";
  is_builtin: boolean;
  kind: "builtin" | "custom";
  is_override: boolean;
  can_edit: boolean;
  can_delete: boolean;
  can_reset: boolean;
  icon_slug: string | null;
  icon_color: string | null;
  name: string;
  description: string | null;
}

export interface TournamentHistoryEntry {
  tournament_id: number;
  tournament_name: string;
  role: string | null;
  division: number | null;
  division_grid_version?: DivisionGridVersion | null;
}

export interface Registration {
  id: number;
  tournament_id: number;
  workspace_id: number;
  auth_user_id: number | null;
  user_id: number | null;
  battle_tag: string | null;
  smurf_tags_json: string[] | null;
  discord_nick: string | null;
  twitch_nick: string | null;
  stream_pov: boolean;
  roles: RegistrationRole[];
  notes: string | null;
  custom_fields_json: Record<string, unknown> | null;
  status: RegistrationStatus;
  status_meta?: StatusMeta;
  balancer_status?: BalancerStatus;
  balancer_status_meta?: StatusMeta;
  checked_in?: boolean;
  profiles_open?: boolean | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  tournament_history?: TournamentHistoryEntry[];
}

export interface RegistrationRole {
  role: string;
  subrole: string | null;
  is_primary: boolean;
  priority: number;
  /** Ordered hero slugs (top picks). */
  top_heroes: string[];
}

export interface RoleInput {
  role: string;
  subrole?: string;
  is_primary: boolean;
  /** Ordered hero slugs (top picks). */
  top_heroes?: string[];
}

export interface RegistrationCreateInput {
  battle_tag?: string;
  smurf_tags?: string[];
  discord_nick?: string;
  twitch_nick?: string;
  roles?: RoleInput[];
  stream_pov?: boolean;
  notes?: string;
  custom_fields?: Record<string, unknown>;
}

export interface RegistrationUpdateInput {
  battle_tag?: string;
  discord_nick?: string;
  twitch_nick?: string;
  primary_role?: string;
  stream_pov?: boolean;
  notes?: string;
  custom_fields?: Record<string, unknown>;
}
