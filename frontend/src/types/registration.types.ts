import type { DivisionGridVersion } from "@/types/workspace.types";

export interface CustomFieldDefinition {
  key: string;
  label: string;
  type: "text" | "number" | "select" | "checkbox" | "url";
  required: boolean;
  placeholder: string | null;
  options: string[] | null;
  validation?: FieldValidationConfig | null;
  /**
   * Surface this answer in the live draft's player inspector. Off by default:
   * the draft board is public, so exposing an answer is an explicit choice.
   */
  show_in_draft?: boolean;
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
  /**
   * Identity fields (battle_tag/discord_nick/twitch_nick) only: when true the
   * submitted handle must match one of the registrant's OAuth-verified social
   * accounts for the field's provider. Implies the field is required.
   */
  require_verified?: boolean;
  /**
   * `flex_role` field only. "forced" is a tournament where role does not
   * matter: the role step hides priorities and every role is submitted as
   * primary. Absent/null == "optional".
   */
  mode?: "optional" | "all_roles" | "forced" | null;
}

export interface SubroleOption {
  slug: string;
  label: string;
}

/** Workspace sub-role catalog keyed by registration role code (tank/dps/support). */
export type SubroleCatalog = Record<string, SubroleOption[]>;

// ---------------------------------------------------------------------------
// Admission — the server's one answer to "is this player in?"
// ---------------------------------------------------------------------------

/** Which gate a requirement blocks at. Ordered: `registration` implies
 *  `check_in` as well, so a registration-stage requirement is checked twice. */
export type AdmissionStage = "registration" | "check_in";

/** The composed decision. Mirrors `shared.services.admission.AdmissionDecision`.
 *
 *  This is the ONLY thing the client may switch on. Five separate re-derivations
 *  of it used to live in the UI — a badge, a grouping key, a sort ordinal, a
 *  search string — and two of them silently disagreed with the other three
 *  because nothing forced them to agree. */
export type AdmissionDecision = "admitted" | "pending_check_in" | "not_admitted";

/** Per-requirement state. Only `blocked` blocks.
 *
 *  `undetermined` fails open by design: a provider outage, an unlinked account
 *  or a token missing a scope must never un-admit a paying subscriber
 *  mid-tournament. `not_applicable` means the tournament switched the
 *  requirement off — such verdicts still ship, because the registrant's
 *  progress steps are built by walking the whole list. */
export type RequirementState = "satisfied" | "blocked" | "undetermined" | "not_applicable";

/** Who can fix a reason. This is what makes an aggregate readable: forty
 *  `undetermined` rows are either forty players who never linked Discord or one
 *  broken role mapping, and the code alone cannot tell an organizer which. */
export type ReasonActor = "player" | "organizer" | "system";

export interface AdmissionReason {
  /** Stable machine code; the UI renders `admission.reason.{code}` and falls
   *  back to the raw code, so a provider added server-side stays explainable. */
  code: string;
  actor: ReasonActor;
  /** What the reason is about — a provider key, or the BattleTag that failed.
   *  Under `open_profile_scope: "all"` a registrant may carry three tags with
   *  exactly one closed, and without this the verdict names none of them. */
  subject?: string | null;
}

export interface RequirementVerdict {
  /** `"open_profile"` | `"subscription"` — open-ended: the registry is
   *  server-side, so a third requirement must not need a client release. */
  key: string;
  state: RequirementState;
  stage: AdmissionStage;
  reasons: AdmissionReason[];
  /** Requirement-shaped extras for the row chips (per-provider verdicts, the
   *  resolved profile scope). Never a decision input. */
  detail: Record<string, unknown>;
}

export interface Admission {
  decision: AdmissionDecision;
  /** Every requirement in registry order, including the switched-off ones. */
  requirements: RequirementVerdict[];
  /** Blocked requirements whose gate has already arrived. Drives `decision`. */
  blockers: RequirementVerdict[];
  /** Blocked requirements the player is admitted DESPITE, because check-in —
   *  the last gate of every requirement — is already behind them.
   *
   *  Word this neutrally: "requirement unmet, admission already granted". It
   *  cannot distinguish an organizer who checked somebody in by hand from a
   *  subscription that lapsed a week after a legitimate check-in, because the
   *  verdicts carry no as-of time. */
  overridden: RequirementVerdict[];
  checked_in: boolean;
  /** `approved` and holding a rank in the balancer pool. Data completeness, not
   *  a requirement, and never spent by check-in. */
  ready: boolean;
}

/** Composed admission answer over the tournament's subscription requirement.
 *  Only `refused` blocks — `undetermined` fails open, exactly like an unknown
 *  `profiles_open`. Mirrors `shared.subscriptions.Outcome` on the backend. */
export type SubscriptionOutcome = "satisfied" | "refused" | "undetermined";

/** Tri-state verdict for one provider. `unknown` never blocks. */
type SubscriptionState = "active" | "inactive" | "unknown";

export interface SubscriptionProviderVerdict {
  state: SubscriptionState;
  tier_rank?: number | null;
  tier_label?: string | null;
  /** Why a verdict is `unknown`; drives the call to action (link Discord vs
   *  reconnect Twitch). Never carries internal evidence like guild/role ids. */
  reason?: string | null;
  /** Whether pasting a code can help HERE. Not inferable from `reason`: under the
   *  permissive method an unlinked patron reads `no_linked_discord_account` and a
   *  code would satisfy them too, so the server has to say so explicitly. */
  code_accepted?: boolean;
}

/** One `{provider, min_tier_rank}` row of the tournament's requirement. */
export interface SubscriptionProviderRequirement {
  provider: string;
  min_tier_rank?: number;
}

/** `{mode, requirements}` as stored in `subscription_requirement_json`.
 *  `any` = one provider is enough, `all` = every listed provider. Each provider
 *  carries its own threshold: Boosty "Уровень 2" and Twitch "Tier 2" are
 *  unrelated scales. */
export interface SubscriptionRequirement {
  mode?: "any" | "all";
  requirements?: SubscriptionProviderRequirement[];
}

/** Response of `GET /tournaments/{id}/subscription/me`. */
export interface SubscriptionStatus {
  required: boolean;
  mode?: "any" | "all" | null;
  outcome?: SubscriptionOutcome | null;
  /** Human-readable rule, e.g. `Boosty уровень 2 или Twitch`. */
  rule?: string | null;
  /** Whether signing up is refused right now. Narrower than `outcome === "refused"`:
   *  a provider the patron can still satisfy with a challenge code is deferred,
   *  because that field only exists at check-in. */
  blocks_registration?: boolean;
  verdicts: Record<string, SubscriptionProviderVerdict>;
}

/** Which mechanism may prove a subscription.
 *
 *  `live` is provider-agnostic on purpose: it means the provider's own signal —
 *  Discord roles for Boosty, the Helix subscriptions endpoint for Twitch. Naming it
 *  after either would be a lie for the other. */
export type VerificationMethod = "live" | "code" | "any";

/** One `discord role -> tier` mapping. `role_id` is a string: a Discord snowflake
 *  exceeds 2**53 and must never round-trip through a float. */
export interface SubscriptionRoleTier {
  role_id: string;
  tier_rank: number;
  tier_label?: string;
}

/** Redacted view of a stored challenge code: never the code, never its digest —
 *  a digest is still brute-forcible offline. */
interface SubscriptionCodeRead {
  tier_rank: number;
  tier_label?: string;
  expires_at?: string | null;
}

/** A code being saved. Plaintext is hashed server-side; the digest form lets the
 *  redacted read model round-trip without double-hashing. */
export interface SubscriptionCodeUpsert {
  code?: string;
  code_sha256?: string;
  tier_rank: number;
  tier_label?: string;
  expires_at?: string | null;
}

export interface SubscriptionProviderConfigRead {
  provider: string;
  enabled: boolean;
  role_tiers: SubscriptionRoleTier[];
  broadcaster_id?: string | null;
  broadcaster_login?: string | null;
  codes: SubscriptionCodeRead[];
  verification_method: VerificationMethod;
}

export interface SubscriptionProviderConfigListResponse {
  configs: SubscriptionProviderConfigRead[];
  /** Response-level, not per-provider: the guild belongs to the workspace, so
   *  every provider that needs one shares this single value. */
  discord_guild_id?: string | null;
}

/** Omitting a field keeps whatever is stored. That matters most for `codes`:
 *  the admin never sees the existing ones, so a plain save must not wipe them. */
export interface SubscriptionProviderConfigUpsert {
  provider: string;
  enabled: boolean;
  role_tiers?: SubscriptionRoleTier[];
  broadcaster_id?: string;
  broadcaster_login?: string;
  codes?: SubscriptionCodeUpsert[];
  verification_method?: VerificationMethod;
}

/** The subscription rule a whole workspace enforces, shared by every tournament
 *  in it. Read and written on the workspace, exactly like the provider config
 *  above: an organizer configures admission once, not per tournament. */
export interface WorkspaceSubscriptionRequirementRead {
  requirement: SubscriptionRequirement;
  /** Live tournaments whose own `require_subscription` toggle is on, i.e. exactly the
   *  set this rule currently gates. Server-computed with the same predicate the
   *  collector sweeps on, so the admin card can quote a real blast radius instead of
   *  warning in the abstract. */
  enforcing_tournaments: number;
}

/** Same shape as the read because the rule is replaced wholesale. A partial
 *  merge of an admission rule would be a silent policy change. */
export interface WorkspaceSubscriptionRequirementUpsert {
  requirement: SubscriptionRequirement;
}

export interface RegistrationForm {
  id: number;
  tournament_id: number;
  workspace_id: number;
  is_open: boolean;
  require_open_profile?: boolean;
  open_profile_scope?: "main" | "all";
  show_ranks?: boolean;
  require_subscription?: boolean;
  subscription_scope?: "player" | "team";
  subscription_stage?: "registration" | "check_in";
  /** Server-resolved from the workspace requirement and read-only — the rule no
   *  longer lives on the form. The check-in dialog renders it, so it stays on
   *  the read model. */
  subscription_requirement_json?: SubscriptionRequirement;
  built_in_fields: Record<string, BuiltInFieldConfig>;
  custom_fields: CustomFieldDefinition[];
  subrole_catalog?: SubroleCatalog;
}

export type RegistrationStatus = string;

type BalancerStatus = string;

export interface TournamentHistoryEntry {
  tournament_id: number;
  tournament_name: string;
  role: string | null;
  division: number | null;
  /** Reference into `RegistrationListResponse.division_grids`. */
  division_grid_version_id?: number | null;
  /** Rehydrated from `division_grids` by `listRegistrations` for in-component use. */
  division_grid_version?: DivisionGridVersion | null;
}

/** Inline team summary carried by every roster row. Mirrors the backend's
 *  `RegistrationTeamBrief`; the full model lives in `registration-team.types.ts`. */
export interface RegistrationTeamBrief {
  id: number;
  name: string;
  status: "forming" | "complete" | "rejected" | "disbanded";
  slot_code: string | null;
  is_substitute: boolean;
  is_captain: boolean;
}

export interface Registration {
  id: number;
  tournament_id: number;
  workspace_id: number;
  user_id: number | null;
  battle_tag: string | null;
  smurf_tags_json: string[] | null;
  discord_nick: string | null;
  twitch_nick: string | null;
  boosty_nick?: string | null;
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
  subscription_outcome?: SubscriptionOutcome | null;
  subscription_verdicts?: Record<string, SubscriptionProviderVerdict> | null;
  /** The composed admission answer. REQUIRED, not optional: the server always
   *  sends it (`AdmissionRead.unknown()` covers a registration nothing was
   *  resolved for), precisely so no consumer writes a null branch. Optional here
   *  would reintroduce per-consumer defaulting, which is how the five deleted
   *  copies of this rule came to exist. */
  admission: Admission;
  /** The registered team this player belongs to, when the tournament runs team
   *  registration. Carries no invites — the public roster must not leak who was
   *  asked and declined. Feeds the participants table's team column and the
   *  "your team is still incomplete" line on the registration card. */
  team?: RegistrationTeamBrief | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  /** Capped to the most recent few entries; see `tournament_history_count` for the true total. */
  tournament_history?: TournamentHistoryEntry[];
  tournament_history_count?: number;
}

/** Envelope returned by `GET /tournaments/{id}/registration/list`. Division grid
 *  versions are deduplicated into `division_grids` (keyed by version id) and
 *  referenced from each history entry via `division_grid_version_id`. */
export interface RegistrationListResponse {
  registrations: Registration[];
  division_grids: Record<string, DivisionGridVersion>;
}

export interface RegistrationRole {
  role: string;
  subrole: string | null;
  is_primary: boolean;
  priority: number;
  rank_value?: number | null;
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
  boosty_nick?: string;
  roles?: RoleInput[];
  stream_pov?: boolean;
  notes?: string;
  custom_fields?: Record<string, unknown>;
}

export interface RegistrationUpdateInput {
  battle_tag?: string;
  discord_nick?: string;
  twitch_nick?: string;
  boosty_nick?: string;
  /* No `primary_role`: the column is long gone (roles are normalized rows now)
     and the server had nowhere to write it. */
  stream_pov?: boolean;
  notes?: string;
  custom_fields?: Record<string, unknown>;
}

/**
 * Registration / balancer status metadata. Lives here rather than in
 * `balancer-admin.types` because the public status badges render it — they had
 * no business importing an admin-only type module.
 */
export type StatusScope = "registration" | "balancer";
export type StatusKind = "builtin" | "custom";

export interface StatusMeta {
  value: string;
  scope: StatusScope;
  is_builtin: boolean;
  kind: StatusKind;
  is_override: boolean;
  can_edit: boolean;
  can_delete: boolean;
  can_reset: boolean;
  icon_slug: string | null;
  icon_color: string | null;
  name: string;
  description: string | null;
  /** Whether a registration currently holding this status counts as part of the balancer pool. */
  excludes_from_balancer: boolean;
  /** Whether a registration currently holding this status is blocked from counting as "ready", independent of excludes_from_balancer. */
  excludes_from_ready: boolean;
}
