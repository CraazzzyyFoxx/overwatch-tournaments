// Session cookie names, namespaced per deployment.
//
// The dev site (`dev.owt.craazzzyyfoxx.me`) is a subdomain of production's
// platform zone, so production's session cookies — written with
// `Domain=.owt.craazzzyyfoxx.me` for cross-subdomain SSO — are ALSO sent to it.
// RFC 6265 keys a cookie by (name, domain, path), but the `Cookie` header
// carries only names and values: two cookies of the same name arrive
// indistinguishable, ordered by path length and then creation time. The older
// production token therefore wins on the dev site, its signature fails against
// the dev JWT secret, and nothing on the dev side can repair it — a delete
// there cannot match production's `Domain`.
//
// One prefix per deployment removes the ambiguity entirely. Default `owt`, so
// production is unchanged; the dev site sets NEXT_PUBLIC_COOKIE_PREFIX=owtdev
// (the Go gateway reads the same value from SESSION_COOKIE_PREFIX). It must be
// set as a BUILD ARG as well as a runtime variable: the client bundle inlines
// it, while SSR, middleware and route handlers read it at runtime.
const PREFIX = process.env.NEXT_PUBLIC_COOKIE_PREFIX || "owt";

export const ACCESS_TOKEN_COOKIE = `${PREFIX}_access_token`;
export const REFRESH_TOKEN_COOKIE = `${PREFIX}_refresh_token`;
export const CSRF_COOKIE = `${PREFIX}_oauth_csrf`;
export const GUARD_COOKIE = `${PREFIX}_xdomain_guard`;

// The aqt_* generation predates the prefix and is read-only (never written), so
// sessions surviving the aqt->owt rename are not logged out. They need no
// prefix: they were always host-only, so they cannot reach another deployment.
export const LEGACY_ACCESS_TOKEN_COOKIE = "aqt_access_token";
export const LEGACY_REFRESH_TOKEN_COOKIE = "aqt_refresh_token";
