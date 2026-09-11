/**
 * Team registration: the pre-formation domain.
 *
 * NOT to be confused with `Team` in `team.types.ts`, which is the POST-balancer
 * materialized `tournament.team` row. These are registered teams that have not
 * been exported yet; the link between the two is `exported_team_id`.
 *
 * Mirrors `backend/tournament-service/src/schemas/registration_team.py`.
 */

import type { RosterSlotCode } from "@/lib/roster-shape";
import type { RegistrationCreateInput } from "@/types/registration.types";

/** A registered team's lifecycle. `complete` is NOT terminal — a captain may
 *  still swap a player before the organizer exports. */
export type RegistrationTeamStatus = "forming" | "complete" | "rejected" | "disbanded";

export type RegistrationTeamInviteState = "pending" | "accepted" | "declined" | "revoked";

export interface RegistrationTeamMember {
  registration_id: number;
  display_name: string | null;
  battle_tag: string | null;
  slot_code: string | null;
  is_substitute: boolean;
  is_captain: boolean;
  is_manager?: boolean;
  checked_in?: boolean;
  status: string;
}

export interface RegistrationTeamInvite {
  id: number;
  slot_code: string;
  is_substitute: boolean;
  state: RegistrationTeamInviteState;
  /**
   * Who a targeted invite was addressed to, as the captain knows them. `null` on a
   * link invite, which has no addressee. This replaced an account id that no
   * client could use: a captain managing two pending offers needs a name, or
   * neither chip can be revoked on purpose.
   */
  target_battle_tag: string | null;
  /** True when the invite is a shareable link. The token itself is never served
   *  again — it is returned exactly once, by the create call. */
  is_link: boolean;
  expires_at: string | null;
  invited_at: string | null;
}

export interface RegistrationTeam {
  id: number;
  tournament_id: number;
  name: string;
  image_url: string | null;
  status: RegistrationTeamStatus;
  captain_registration_id: number | null;
  exported_team_id: number | null;
  members: RegistrationTeamMember[];
  /** Only populated for the captain's own view and the organizer's — the public
   *  roster omits them server-side so it cannot leak who declined. */
  invites: RegistrationTeamInvite[];
  /** Slots with nobody accepted yet. Empty object means the roster is complete.
   *  Zero-count entries are stripped server-side. */
  open_slots: Partial<Record<RosterSlotCode, number>>;
  /** Server-rendered "what is still missing", e.g. "1x dps, 2x support". */
  shortfall: string;
  is_complete: boolean;
  substitutes_used: number;
  max_substitutes: number;
  admission?: "pending" | "accepted" | "waitlisted";
  rejection_reason?: string | null;
  organizer_notes?: string | null;
  roster_locked_at?: string | null;
  subscription_covered?: boolean;
  subscription_expires_at?: string | null;
  checked_in_count?: number;
  check_in_total?: number;
  eligibility_issues?: { code: string; registration_id: number | null; blocking: boolean }[];
}

export interface RegistrationTeamListResponse {
  items: RegistrationTeam[];
  total: number;
  /** Live registrations on no team — the free agents. The export cannot place
   *  them: it materializes registered teams only, and on a team-registration
   *  tournament neither the balancer nor the draft runs. */
  unassigned_players: number;
}

/** What the organizer's export reports back: teams materialized into
 *  `tournament.team`, the rows it replaced, the players it created, and every
 *  roster it refused with the code saying why. */
export interface RegistrationTeamExportResult {
  removed_teams: number;
  imported_teams: number;
  created_players: number;
  skipped: { team_id: number; name: string; code: string }[];
}

/** The raw invite token rides back exactly once, alongside the created invite. */
export interface RegistrationTeamInviteCreated extends RegistrationTeamInvite {
  token: string | null;
}

// ── request payloads ────────────────────────────────────────────────────────

export interface RegistrationTeamCreateInput {
  name: string;
  /** The slot the captain personally occupies — they are a member like any other. */
  slot_code: RosterSlotCode;
  /** Identical shape to a solo registration; the backend runs the same validation. */
  registration: RegistrationCreateInput;
}

export interface RegistrationTeamInviteInput {
  slot_code: RosterSlotCode;
  is_substitute?: boolean;
  /**
   * Omit for a shareable link invite; set to address a free agent already
   * registered for this tournament.
   *
   * A REGISTRATION id, not an account id. The captain picks from this tournament's
   * own free agents, so the picker opens no new identity surface, and the server
   * resolves the account behind it.
   */
  target_registration_id?: number | null;
  ttl_days?: number | null;
}

export interface RegistrationTeamAcceptInput {
  /** Exactly one of `token` / `invite_id` — the backend rejects both or neither. */
  token?: string;
  invite_id?: number;
  /**
   * Omit when the invitee already has a live registration: the backend attaches
   * that row and ignores anything sent here, so there is no form left to answer.
   * It used to be required-but-ignored, which forced callers to cast an empty
   * object — a lie the type system could not catch.
   */
  registration?: RegistrationCreateInput;
}

/**
 * What a shared invite link reveals before its holder signs in.
 *
 * Deliberately roster-free: whoever holds the token is not a member yet. It
 * carries `state` AND `is_redeemable` because those answer different questions —
 * the state says what happened to the invite, redeemability says whether the
 * accept form is worth showing. An expired-but-pending invite is both.
 */
export interface RegistrationTeamInvitePreview {
  tournament_id: number;
  tournament_name: string;
  workspace_id: number;
  team_id: number;
  team_name: string;
  slot_code: string;
  is_substitute: boolean;
  state: string;
  expires_at: string | null;
  /** Server-computed: the client's clock is not the one the accept guard uses. */
  is_redeemable: boolean;
}

/**
 * A registrant on no team, as the captain's invite picker lists them.
 *
 * Everything here is already on the public participants list — the account
 * requirement on the endpoint exists because the only use of this list is to act
 * on it, not because the data is sensitive.
 */
export interface RegistrationFreeAgent {
  registration_id: number;
  battle_tag: string;
  /** Role codes, primary first: the captain is filling one specific slot. */
  roles: string[];
}

export interface RegistrationFreeAgentListResponse {
  items: RegistrationFreeAgent[];
  total: number;
}

/**
 * An invite addressed to the current user.
 *
 * Distinct from `RegistrationTeamInvitePreview`, which answers the same question
 * for a LINK held by a stranger. A targeted invite carries no token at all, so
 * this read is the only way its recipient can learn it exists.
 */
export interface RegistrationTeamInviteOffer {
  invite_id: number;
  team_id: number;
  team_name: string;
  slot_code: string;
  is_substitute: boolean;
  expires_at: string | null;
}

export interface RegistrationTeamInviteOfferListResponse {
  items: RegistrationTeamInviteOffer[];
}

/**
 * One invite a team ever issued, live or finished.
 *
 * Distinct from `RegistrationTeamInvite`, which is the LIVE list whose rows
 * reserve roster slots. A terminal row must never appear there — a declined
 * offer holding a place open is the bug that separation prevents.
 */
export interface RegistrationTeamInviteHistoryEntry {
  id: number;
  slot_code: string;
  is_substitute: boolean;
  /** Includes `expired`, which is derived from a pending row past its clock. */
  state: string;
  target_battle_tag: string | null;
  is_link: boolean;
  invited_at: string | null;
  expires_at: string | null;
  /** When it stopped being open, if anything closed it. */
  answered_at: string | null;
  /** Staff withdrew it rather than the captain. Same state, different event. */
  revoked_by_organizer: boolean;
}

/**
 * The history and the cap standing it explains.
 *
 * They ship together because apart they are a riddle: the cap counts every
 * invite ever issued while only pending ones were ever visible, so a captain
 * refused at the ceiling had no way to see where it went.
 */
export interface RegistrationTeamInviteHistoryResponse {
  items: RegistrationTeamInviteHistoryEntry[];
  cap_used: number;
  cap_limit: number;
  /** Set when an organizer forgave the count; the rows before it remain listed. */
  cap_reset_at: string | null;
}
