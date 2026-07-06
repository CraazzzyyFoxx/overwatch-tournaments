import { NextResponse } from "next/server";
import { PLATFORM_ZONE } from "./host";

// Canonical cookie names, written by oauth-callback.ts (login) and
// auth/refresh/route.ts (refresh). LEGACY_* names are read as a fallback
// during the aqt->owt rename so existing sessions are not logged out; they
// are never written, only read and cleared.
export const ACCESS_TOKEN_COOKIE = "owt_access_token";
export const REFRESH_TOKEN_COOKIE = "owt_refresh_token";
const LEGACY_ACCESS_TOKEN_COOKIE = "aqt_access_token";
const LEGACY_REFRESH_TOKEN_COOKIE = "aqt_refresh_token";

const IS_PROD = process.env.NODE_ENV === "production";
// owt_access_token/owt_refresh_token are set Domain-wide (SSO across
// subdomains) by oauth-callback.ts / auth/refresh/route.ts. A delete here
// without the same Domain attribute doesn't clear that cookie — RFC 6265
// keys a cookie by (name, domain, path), so a host-only delete would leave
// the real domain-wide cookie in place (session resurrection) instead of
// clearing it. Must match exactly.
const COOKIE_DOMAIN = `.${PLATFORM_ZONE}`;

// Minimal structural type covering `await cookies()` (the
// `ReadonlyRequestCookies` result of `next/headers`'s `cookies()`) without
// depending on that type, which isn't re-exported from the public
// `next/headers` entrypoint.
interface CookieStore {
  get(name: string): { value: string } | undefined;
}

// Deletes a Domain-wide `owt_*` cookie, replicating the exact attributes it
// was set with so the browser treats this as an overwrite of the real
// cookie rather than creating a second, competing one.
function deleteOwtCookie(response: NextResponse, name: string): void {
  response.cookies.delete({
    name,
    path: "/",
    ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {}),
  });
}

// Reads the access-token cookie, preferring the canonical `owt_access_token`
// name and falling back to the legacy `aqt_access_token` name so existing
// sessions survive the aqt->owt rename.
export function getAccessToken(store: CookieStore): string | undefined {
  return store.get(ACCESS_TOKEN_COOKIE)?.value ?? store.get(LEGACY_ACCESS_TOKEN_COOKIE)?.value;
}

// Reads the refresh-token cookie with the same owt->aqt fallback as
// getAccessToken.
export function getRefreshToken(store: CookieStore): string | undefined {
  return store.get(REFRESH_TOKEN_COOKIE)?.value ?? store.get(LEGACY_REFRESH_TOKEN_COOKIE)?.value;
}

// Clears BOTH generations of BOTH tokens on `response`. owt_* are
// Domain-wide cookies in production — a delete without the same Domain
// attribute creates a second, host-only cookie of the same name instead of
// clearing the real one (RFC 6265 keys a cookie by name+domain+path), which
// would leave the user silently still logged in on every subdomain (session
// resurrection). aqt_* were always host-only, so a plain delete suffices for
// them. Callers must route every "log the user out" site through this
// helper so a partial future edit can't reintroduce that gap.
export function clearAuthCookies(response: NextResponse): void {
  deleteOwtCookie(response, ACCESS_TOKEN_COOKIE);
  deleteOwtCookie(response, REFRESH_TOKEN_COOKIE);
  response.cookies.delete(LEGACY_ACCESS_TOKEN_COOKIE);
  response.cookies.delete(LEGACY_REFRESH_TOKEN_COOKIE);
}
