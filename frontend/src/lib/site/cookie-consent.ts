/**
 * Analytics-cookie consent, stored in a first-party cookie rather than
 * `localStorage` so the root layout can read the decision during the initial
 * server render: a returning visitor never sees the notice flash in, and the
 * Google Analytics tag is only emitted for someone who accepted it.
 *
 * Functional cookies (session, active workspace, locale) are out of scope —
 * the site cannot work without them, so there is nothing to consent to.
 */
export const COOKIE_CONSENT_COOKIE = "owt-cookie-consent";

/** Six months, after which the notice asks again. */
export const COOKIE_CONSENT_TTL_DAYS = 180;

/** An absent or unrecognized cookie means "not decided yet" (`null`). */
export type CookieConsentValue = "accepted" | "declined";
