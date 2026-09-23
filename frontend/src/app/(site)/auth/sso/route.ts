import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { authService } from "@/services/auth.service";
import { getTokenMaxAgeSeconds } from "@/lib/auth/jwt";
import {
  FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS,
  REFRESH_COOKIE_MAX_AGE_SECONDS,
  clearGuardCookie,
  guardTicketErrorRedirect,
  safeRedirectTarget
} from "@/lib/auth/oauth-callback";
import { ACCESS_TOKEN_COOKIE, GUARD_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth/cookie-names";
import { publicOrigin } from "@/lib/site/request-origin";

const IS_PROD = process.env.NODE_ENV === "production";

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
// GUARD_COOKIE (read below, cleared via clearGuardCookie) follows the same
// host-only rule -- see lib/auth/oauth-callback.ts for the shared definition and
// clear helper, which /auth/link/complete/route.ts also uses.

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
    return guardTicketErrorRedirect(currentOrigin, "invalid_state");
  }

  const cookieStore = await cookies();
  const guard = cookieStore.get(GUARD_COOKIE)?.value;

  // Fail closed: with no guard cookie there is nothing to bind this
  // redemption to the browser that started the flow (Task 10R fix 1) --
  // identity-svc would reject a missing `guard` anyway, but there's no
  // reason to spend an RPC round trip (and burn the single-use ticket) on a
  // request that's already missing something required.
  if (!guard) {
    return guardTicketErrorRedirect(currentOrigin, "invalid_state");
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
    return guardTicketErrorRedirect(currentOrigin, "exchange_failed");
  }
}
