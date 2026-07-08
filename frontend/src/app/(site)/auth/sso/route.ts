import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { authService } from "@/services/auth.service";
import { getTokenMaxAgeSeconds } from "@/lib/jwt";
import {
  FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS,
  REFRESH_COOKIE_MAX_AGE_SECONDS,
  safeRedirectTarget
} from "@/lib/oauth-callback";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth-cookies";
import { publicOrigin } from "@/lib/request-origin";

const IS_PROD = process.env.NODE_ENV === "production";

// Task 10R fix 1: the single-use, HOST-ONLY guard cookie set by
// oauth-login.ts's custom-domain apex bounce, on THIS exact domain, before
// the flow ever left for the apex. Its raw value is the credential this
// route must present alongside the ticket -- see the module docstring in
// oauth-login.ts for the full browser-binding rationale. Read once here,
// forwarded raw to identity-svc, then always cleared (single use, same as
// owt_oauth_csrf).
const GUARD_COOKIE = "owt_xdomain_guard";

// Far side of the custom-domain SSO ticket handoff (Task 9). This route runs
// ON the workspace's custom domain itself — never the platform apex — after
// oauth-callback.ts's ticket branch has already authoritatively verified
// (via `isVerifiedTenantOrigin`/`by_host`) that this exact origin is a real,
// resolvable workspace before ever redirecting the browser here. That check
// happened once, upstream; this route trusts it and focuses on redeeming the
// ticket and establishing the session locally.
//
// Cookies set here are HOST-ONLY (no `domain` attribute): unlike
// oauth-callback.ts's `Domain=.owt` cookies, which are readable across every
// platform subdomain, this domain is a foreign registrable domain from the
// platform's point of view — the browser would reject a cross-domain
// `Set-Cookie` anyway, and a host-only cookie is the correct scope regardless.
// The GUARD_COOKIE clear below follows the same host-only rule -- it must
// NEVER carry a `domain` attribute, or the delete won't match the cookie
// oauth-login.ts actually set.
function clearGuardCookie(response: NextResponse): void {
  response.cookies.delete({ name: GUARD_COOKIE, path: "/" });
}

function errorRedirect(origin: string, errorCode: string): NextResponse {
  const errorUrl = new URL("/", origin);
  errorUrl.searchParams.set("auth_error", errorCode);
  const response = NextResponse.redirect(errorUrl);
  clearGuardCookie(response);
  return response;
}

export async function GET(request: Request) {
  // This route runs ON the workspace's custom domain. `request.url`'s host
  // behind the edge is the internal bind addr (0.0.0.0:3000), so derive the
  // real origin from the forwarded headers — otherwise the post-login redirect
  // (and error redirects) would send the user to https://0.0.0.0:3000. See
  // request-origin.ts.
  const currentOrigin = publicOrigin(request);
  const searchParams = new URL(request.url).searchParams;
  const ticket = searchParams.get("ticket");
  const next = searchParams.get("next") ?? "";

  if (!ticket) {
    return errorRedirect(currentOrigin, "invalid_state");
  }

  const cookieStore = await cookies();
  const guard = cookieStore.get(GUARD_COOKIE)?.value;

  // Fail closed: with no guard cookie there is nothing to bind this
  // redemption to the browser that started the flow (Task 10R fix 1) --
  // identity-svc would reject a missing `guard` anyway, but there's no
  // reason to spend an RPC round trip (and burn the single-use ticket) on a
  // request that's already missing something required.
  if (!guard) {
    return errorRedirect(currentOrigin, "invalid_state");
  }

  try {
    const tokens = await authService.ssoExchange(ticket, guard);
    const target = safeRedirectTarget(next, currentOrigin);

    const response = NextResponse.redirect(target);

    // No `domain` on either cookie below: host-only, see file header comment.
    response.cookies.set(ACCESS_TOKEN_COOKIE, tokens.access_token, {
      httpOnly: false,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: getTokenMaxAgeSeconds(tokens.access_token, FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS)
    });

    response.cookies.set(REFRESH_TOKEN_COOKIE, tokens.refresh_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: REFRESH_COOKIE_MAX_AGE_SECONDS
    });

    clearGuardCookie(response);
    return response;
  } catch (err) {
    console.error("SSO ticket exchange error:", err);
    return errorRedirect(currentOrigin, "exchange_failed");
  }
}
