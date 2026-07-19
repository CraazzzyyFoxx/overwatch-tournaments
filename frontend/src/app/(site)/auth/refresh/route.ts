import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { getTokenMaxAgeSeconds } from "@/lib/jwt";
import { authService } from "@/services/auth.service";
import { PLATFORM_ZONE, isPlatformHost } from "@/lib/host";
import { clearAuthCookies, getRefreshToken } from "@/lib/auth-cookies";
import { publicHostname } from "@/lib/request-origin";

// Cookie lifetime used when the access token's `exp` can't be decoded.
const FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS = 13 * 60;

const IS_PROD = process.env.NODE_ENV === "production";
// owt_access_token/owt_refresh_token are set Domain-wide (SSO across
// subdomains) by oauth-callback.ts. A set here without the same Domain
// attribute doesn't overwrite that cookie — RFC 6265 keys a cookie by
// (name, domain, path), so a host-only Set-Cookie would create a *second*,
// competing cookie of the same name instead of refreshing the real one.
// Must match exactly.
const COOKIE_DOMAIN = `.${PLATFORM_ZONE}`;

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const refreshToken = getRefreshToken(cookieStore);

  if (!refreshToken) {
    const response = NextResponse.json({ message: "Missing refresh token" }, { status: 401 });
    clearAuthCookies(response);
    return response;
  }

  try {
    const tokens = await authService.refresh(refreshToken, getForwardedClientHeaders(request));

    const response = NextResponse.json(tokens, { status: 200 });

    // Domain-wide (`.owt`) ONLY on the platform apex/subdomains (SSO across
    // subdomains). On a workspace CUSTOM domain the browser rejects a `.owt`
    // cookie, so it must be host-only — otherwise the refreshed token is
    // dropped and the session can't be sustained. Matches /auth/sso, which sets
    // the login cookies host-only there.
    const domainAttr = IS_PROD && isPlatformHost(publicHostname(request)) ? { domain: COOKIE_DOMAIN } : {};

    response.cookies.set("owt_access_token", tokens.access_token, {
      httpOnly: false,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: getTokenMaxAgeSeconds(tokens.access_token, FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS),
      ...domainAttr
    });

    response.cookies.set("owt_refresh_token", tokens.refresh_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: 30 * 24 * 60 * 60,
      ...domainAttr
    });

    return response;
  } catch {
    const response = NextResponse.json({ message: "Failed to refresh" }, { status: 401 });
    clearAuthCookies(response);
    return response;
  }
}
