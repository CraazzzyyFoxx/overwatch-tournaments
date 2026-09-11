/**
 * Backend machine error codes → translated UI strings.
 *
 * §12.2 of the team-registration design: `friendlyMessage` in `api-error.ts`
 * prefers the server's `msg` **verbatim**, and every backend message is English.
 * The captain and invitee flows are public and the audience is Russian-first, so
 * rendering `msg` would ship English error text to Russian users. Every rejection
 * from these flows therefore carries a stable `code`, and this module is the only
 * place that turns one into text.
 *
 * This is the first code→i18n mapping in the codebase. It is deliberately scoped
 * to this feature rather than added to `ERROR_CODE_MESSAGES`, which is a small
 * English-only generic fallback table and not locale-aware.
 *
 * Unknown codes use a localized recovery message, never raw server text.
 */

import { ApiError } from "@/lib/api-error";

/**
 * Every code the team-registration flows can return, grouped by origin.
 *
 * Exhaustive on purpose: `registration-team-errors.test.ts` asserts that each one
 * has a leaf in BOTH message dictionaries, which is the only way a missing
 * translation is caught before a user hits it.
 */
export const REGISTRATION_TEAM_ERROR_CODES = [
  "request_failed",
  // team creation / naming
  "team_name_required",
  "team_name_invalid",
  "team_name_taken",
  "already_registered",
  "registration_terminal",
  "registration_closed",
  // lookup / lifecycle
  "team_not_found",
  "tournament_not_found",
  "team_already_exported",
  "team_not_forming",
  "team_has_no_captain",
  // authorization
  "not_captain",
  "invite_not_for_you",
  // roster edits
  "member_not_found",
  "cannot_kick_captain",
  "captain_must_transfer",
  "captain_must_be_starter",
  // slots
  "slot_taken",
  "slot_already_offered",
  "bench_full",
  "slot_not_in_shape",
  "roster_slots_unknown_code",
  // invites
  "invite_not_found",
  "invite_reference_required",
  "invite_expired",
  "invite_revoked",
  "invite_declined",
  "invite_already_accepted",
  "invite_cap_reached",
  // targeted invites — a captain picks a free agent, and the snapshot they picked
  // from can be stale by the time they press invite. `player_not_free` is
  // therefore an ordinary outcome, not an edge case, and untranslated it would
  // read as an English server message on a Russian-first surface.
  "registration_not_found",
  "player_not_free",
  "player_has_no_account",
  // throttling
  "invite_rate_limited",
  "accept_rate_limited",
  "rate_limit_unavailable",
  "roster_locked",
  "team_not_complete",
  "check_in_closed",
  "member_not_approved",
  "subscription_not_team_scoped",
  "subscription_not_active",
  "admission_invalid",
  "invite_not_a_link",
  "captain_is_not_manager",
  "cannot_move_captain",
  "team_rank_unrated",
  "team_rank_too_low",
  "team_rank_too_high",
  "team_rank_spread",
  "team_identity_taken",
  "discord_guild_not_configured",
  "discord_not_linked",
  "discord_guild_not_member",
  "discord_guild_unreachable",
] as const;

export type RegistrationTeamErrorCode = (typeof REGISTRATION_TEAM_ERROR_CODES)[number];

/** Static membership table — a `Record`, not a `Set`: nothing is ever inserted at
 *  runtime and no iterator API is needed. */
const KNOWN_CODES: Record<string, true> = Object.fromEntries(
  REGISTRATION_TEAM_ERROR_CODES.map((code) => [code, true] as const),
);

/**
 * A next-intl translator scoped to `registrationTeams.errors`.
 *
 * The key type is the code union, not `string`: the project types its messages,
 * so `useTranslations("registrationTeams.errors")` only accepts keys that exist —
 * and a narrow-key function is not assignable to a wide-key parameter. Declaring
 * the union both accepts the real translator and makes a missing key a *type*
 * error rather than a runtime fallback.
 *
 * `has` is optional so a plain function (or a test double) still works; when it is
 * absent the known-code table is used as the membership test instead, which is why
 * that list must stay exhaustive.
 */
export type ErrorTranslator = ((key: RegistrationTeamErrorCode) => string) & {
  // Narrow for the same reason as the call signature: next-intl types `has` on
  // the namespace's key union, so a `(key: string) => boolean` shape rejects it.
  has?: (key: RegistrationTeamErrorCode) => boolean;
};

/**
 * The translated message for a thrown error, or the generic fallback.
 *
 * Codes are checked in the order the server sent them, so the first *recognized*
 * one wins — a response carrying both a specific code and a generic one reads as
 * the specific one.
 */
export function translateRegistrationTeamError(
  t: ErrorTranslator,
  error: unknown,
  fallback?: string,
): string {
  if (error instanceof ApiError) {
    for (const detail of error.details) {
      if (!detail.code) continue;
      // Cast once: `detail.code` is an untyped wire string, and both the
      // membership test and the lookup below are keyed on the code union. The
      // cast is safe because only a code the dictionary holds gets used.
      const code = detail.code as RegistrationTeamErrorCode;
      // `t.has` when the translator provides it (next-intl does), otherwise the
      // static table — which is why it must stay exhaustive.
      const translatable = typeof t.has === "function" ? t.has(code) : KNOWN_CODES[code];
      if (translatable) return t(code);
    }
  }
  return fallback ?? t("request_failed");
}

/** The machine code of a thrown error, when it is one this feature knows. */
export function registrationTeamErrorCode(error: unknown): RegistrationTeamErrorCode | null {
  if (!(error instanceof ApiError)) return null;
  for (const detail of error.details) {
    if (detail.code && KNOWN_CODES[detail.code]) {
      return detail.code as RegistrationTeamErrorCode;
    }
  }
  return null;
}

/**
 * True when retrying the same request could plausibly succeed later.
 *
 * Drives whether a form shows a "try again" affordance: a throttle or a Redis
 * outage clears on its own, while `slot_taken` or `team_name_taken` needs the user
 * to change something first.
 */
export function isRetryableRegistrationTeamError(error: unknown): boolean {
  const code = registrationTeamErrorCode(error);
  return (
    code === "invite_rate_limited" ||
    code === "accept_rate_limited" ||
    code === "rate_limit_unavailable"
  );
}
