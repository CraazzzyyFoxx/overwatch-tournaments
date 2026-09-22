import type {
  Admission,
  AdmissionDecision,
  AdmissionReason,
  RequirementVerdict
} from "@/types/registration.types";

/**
 * Projections of the server's ONE admission answer.
 *
 * Every consumer needs a different shape of the same decision — a badge wants
 * three states, the sort column wants an ordinal, the search index wants text,
 * the registrant's progress steps want one entry per requirement. Those shapes
 * live here, derived from `admission.decision` and `admission.requirements`, so
 * that they cannot drift from each other the way the five hand-written
 * re-derivations they replaced
 * did: two of those deliberately ignored the subscription condition their own
 * cell rendered.
 *
 * Nothing here re-computes admission. If a function in this file ever reads
 * `status`, `balancer_status`, `profiles_open` or `subscription_outcome`, it has
 * become a sixth copy.
 */

/** Sort ordinal for the admission column: worst first, so ascending order reads
 *  "who needs attention" top-down. */
export const ADMISSION_ORDER: Record<AdmissionDecision, number> = {
  not_admitted: 0,
  pending_check_in: 1,
  admitted: 2
};

/** Free-text projection for the table's client-side search box. */
export const ADMISSION_SEARCH_TEXT: Record<AdmissionDecision, string> = {
  not_admitted: "not admitted",
  pending_check_in: "check-in pending",
  admitted: "admitted"
};

/**
 * Every reason code the backend's `REASON_ACTORS` map holds, plus the `unknown`
 * sentinel `reason()` substitutes when a verdict carries no code at all.
 *
 * Duplicated from Python on purpose: it is the membership test for translators
 * that do not implement `t.has` (the test doubles), and the source of the key
 * union below. `admission.test.ts` pins it against both message files, so a code
 * added on one side surfaces as a failing test rather than as raw snake_case in
 * the UI.
 */
export const ADMISSION_REASON_CODES = [
  // open_profile, derived from `battle_tag_state.status`
  "no_battle_tag",
  "never_fetched",
  "collection_pending",
  "collection_failed",
  "collection_disabled",
  "profile_private",
  "profile_not_found",
  // subscription, as the providers emit them
  "no_linked_discord_account",
  "no_linked_twitch_account",
  "missing_scope",
  "not_subscribed",
  "not_a_member",
  "no_mapped_role",
  "no_code_redeemed",
  "guild_not_configured",
  "no_role_tiers_configured",
  "role_mapping_drift",
  "broadcaster_not_configured",
  "twitch_client_not_configured",
  "broadcaster_not_eligible",
  "provider_unavailable",
  "guild_not_accessible",
  "bot_not_configured",
  "cache_not_ready",
  // a verdict that carried no reason at all — a provider bug, surfaced as one
  "unknown"
] as const;

export type AdmissionReasonCode = (typeof ADMISSION_REASON_CODES)[number];

/** Membership test for translators without `t.has`. A `Record` rather than a
 *  `Set` per project convention for static string-keyed tables; built from the
 *  list above so the two can never disagree. */
const KNOWN_REASON_CODES: Record<string, true> = Object.fromEntries(
  ADMISSION_REASON_CODES.map((code) => [code, true])
);

type ReasonKey = `admission.reason.${AdmissionReasonCode}`;

/**
 * The slice of next-intl's translator these helpers need.
 *
 * Narrowed to the reason-key union rather than `(key: string) => string` for the
 * same reason as `ErrorTranslator` in `registration-team-errors`: next-intl
 * types both the call and `has` on the message-key union, so a `string`
 * parameter rejects it. `has` is optional because test doubles are plain
 * functions — those fall back to `KNOWN_REASON_CODES`, which is why that list
 * must stay complete.
 */
export type AdmissionTranslator = ((key: ReasonKey) => string) & {
  has?: (key: ReasonKey) => boolean;
};

/**
 * Human text for one reason, never empty.
 *
 * An unrecognised code renders as itself: a provider added server-side stays
 * explainable without a client deploy, and a blank cell would read as "nothing
 * wrong here" — the opposite of the truth.
 *
 * `subject` is appended in parentheses whenever the server attached one, which is
 * exactly where it disambiguates: WHICH of three smurf tags is closed, WHICH
 * provider is down. A per-code ICU placeholder was the alternative and was
 * rejected — half the codes carry no subject, so every message would need a
 * subject-less twin.
 */
export function formatAdmissionReason(t: AdmissionTranslator, reason: AdmissionReason): string {
  const key: ReasonKey = `admission.reason.${reason.code as AdmissionReasonCode}`;
  const known =
    typeof t.has === "function" ? t.has(key) : KNOWN_REASON_CODES[reason.code] === true;
  const label = known ? t(key) : reason.code;
  return reason.subject ? `${label} (${reason.subject})` : label;
}

/** Human name for a requirement, for the step whose state needs no explaining.
 *  Falls back to the raw registry key, so a third requirement is legible on the
 *  day the server starts sending it. */
export function formatRequirementName(t: AdmissionTranslator, key: string): string {
  // The registry lives server-side, so a requirement key is NOT a member of the
  // catalogue's compile-time key union — deliberately: a third requirement must
  // not need a client release. `t.has` is the runtime check that makes the cast
  // safe, the same discipline `translateRegistrationTeamError` uses on an
  // untyped wire code. Without `has` (test doubles) the raw key is the only
  // honest answer.
  const messageKey = `admission.requirement.${key}` as ReasonKey;
  return typeof t.has === "function" && t.has(messageKey) ? t(messageKey) : key;
}

/**
 * The one reason to put in a per-row cell.
 *
 * A blocker first — that is what is keeping the player out — then the first
 * merely-undetermined requirement, which is the organizer's early warning: it is
 * failing open right now and will keep doing so until somebody looks.
 */
export function primaryAdmissionReason(admission: Admission): AdmissionReason | null {
  const blocker = admission.blockers.find((requirement) => requirement.reasons.length > 0);
  if (blocker) return blocker.reasons[0];
  const pending = admission.requirements.find(
    (requirement) => requirement.state === "undetermined" && requirement.reasons.length > 0
  );
  return pending?.reasons[0] ?? null;
}

/** Requirements the registrant's progress chain shows: everything the tournament
 *  actually switched on, in registry order. */
export function activeRequirements(admission: Admission): RequirementVerdict[] {
  return admission.requirements.filter(
    (requirement) => requirement.state !== "not_applicable"
  );
}
