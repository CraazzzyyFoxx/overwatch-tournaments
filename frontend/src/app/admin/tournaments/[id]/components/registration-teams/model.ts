import { type Tone } from "@/components/kit/tone";
import type {
  RegistrationTeam,
  RegistrationTeamInvite,
  RegistrationTeamMember
} from "@/types/registration-team.types";

/**
 * The vocabulary the organizer's teams browser reads its rows with: the tones
 * of every lifecycle word, and the few derivations a row needs before it can be
 * rendered or acted on.
 *
 * Pure on purpose — no hooks, no JSX. The table, the inspector and the
 * confirmations all decide from these, and a derivation that lives in one of
 * them is a derivation the other two copy.
 */

export const EXPIRY_STAMP = {
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit"
} as const;

export const EXPORT_SKIP_CODES = [
  "team_incomplete",
  "team_empty",
  "team_waitlisted",
  "team_subscription_uncovered"
] as const;

/** The states the ledger names. Anything outside it renders raw: the server
 *  derives `expired` from a pending row past its clock and may add more, and an
 *  untranslated word beats a missing message path on screen. */
export const HISTORY_STATES = ["pending", "accepted", "declined", "revoked", "expired"] as const;

const INVITE_TONE: Record<(typeof HISTORY_STATES)[number], Tone> = {
  pending: "warning",
  accepted: "success",
  declined: "danger",
  revoked: "neutral",
  expired: "neutral"
};

export function inviteTone(state: string): Tone {
  const known = HISTORY_STATES.find((candidate) => candidate === state);
  return known ? INVITE_TONE[known] : "neutral";
}

/** Lifecycle tone for the admin's own pill vocabulary. The public surfaces use
 *  `REGISTRATION_TEAM_STATUS_TONE` (raw classes); `StatusPill` takes a `Tone`. */
export const TEAM_STATUS_TONE: Record<string, Tone> = {
  forming: "warning",
  complete: "success",
  exported: "info",
  rejected: "danger",
  disbanded: "neutral"
};

export const ADMISSION_TONE: Record<string, Tone> = {
  pending: "warning",
  accepted: "success",
  waitlisted: "neutral"
};

export function memberName(member: RegistrationTeamMember): string {
  return member.display_name ?? member.battle_tag ?? `#${member.registration_id}`;
}

/** The one member every organizer view identifies a team by. */
export function captainOf(team: RegistrationTeam): RegistrationTeamMember | undefined {
  return team.members.find((member) => member.is_captain);
}

/**
 * Starters on the roster, and how many the tournament's shape asks for.
 *
 * `required` is not a field: the server sends what is still open, so the target
 * is the starters already placed plus those holes.
 */
export function rosterCounts(team: RegistrationTeam): { starters: number; required: number } {
  const starters = team.members.filter((member) => !member.is_substitute).length;
  const open = Object.values(team.open_slots).reduce((sum, count) => sum + (count ?? 0), 0);
  return { starters, required: starters + open };
}

/**
 * An invite an organizer can still withdraw: anything terminal, or a pending
 * one already past its clock, is out of everybody's hands.
 *
 * Its own function because the clock is read here: `Date.now()` inside the JSX
 * is an impure render (`react-hooks/purity`), same as `getApiKeyStatus` in
 * `access/api-keys`.
 */
export function isLiveInvite(invite: RegistrationTeamInvite): boolean {
  return (
    invite.state === "pending" &&
    (!invite.expires_at || new Date(invite.expires_at).getTime() > Date.now())
  );
}

/** A roster the server would actually materialize into `tournament.team`. */
export function isExportEligible(team: RegistrationTeam): boolean {
  return (
    team.status === "complete" &&
    team.is_complete &&
    team.admission !== "waitlisted" &&
    !team.eligibility_issues?.some((issue) => issue.blocking)
  );
}

/** Still the captain's to change: not exported, not terminal. */
export function isTeamLive(team: RegistrationTeam): boolean {
  return team.status === "forming" || team.status === "complete";
}

/**
 * What the screen's single `ConfirmDialog` is currently asking.
 *
 * One mount with a swapped intent, not four near-identical `AlertDialog`s whose
 * only difference was their strings. `export` carries the teams it named back
 * to the organizer (and the table's `clear`, so a confirmed export drops the
 * selection it consumed); `reject` carries the team whose captain will read the
 * reason.
 */
export type PendingConfirm =
  | { kind: "reject"; team: RegistrationTeam }
  | { kind: "unlock"; team: RegistrationTeam }
  | { kind: "resetCap"; team: RegistrationTeam }
  | { kind: "export"; teams: RegistrationTeam[]; clear?: () => void };
