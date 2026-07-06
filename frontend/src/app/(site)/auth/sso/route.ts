import { NextResponse } from "next/server";
import { authService } from "@/services/auth.service";
import { getTokenMaxAgeSeconds } from "@/lib/jwt";
import {
  FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS,
  REFRESH_COOKIE_MAX_AGE_SECONDS,
  safeRedirectTarget
} from "@/lib/oauth-callback";
import { ACCESS_TOKEN_COOKIE, REFRESH_TOKEN_COOKIE } from "@/lib/auth-cookies";

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
function errorRedirect(origin: string, errorCode: string): NextResponse {
  const errorUrl = new URL("/", origin);
  errorUrl.searchParams.set("auth_error", errorCode);
  return NextResponse.redirect(errorUrl);
}

export async function GET(request: Request) {
  const { origin: currentOrigin, searchParams } = new URL(request.url);
  const ticket = searchParams.get("ticket");
  const next = searchParams.get("next") ?? "";

  if (!ticket) {
    return errorRedirect(currentOrigin, "invalid_state");
  }

  try {
    const tokens = await authService.ssoExchange(ticket);
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

    return response;
  } catch (err) {
    console.error("SSO ticket exchange error:", err);
    return errorRedirect(currentOrigin, "exchange_failed");
  }
}
