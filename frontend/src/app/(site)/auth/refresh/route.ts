import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { getTokenMaxAgeSeconds } from "@/lib/jwt";
import { authService } from "@/services/auth.service";
import { PLATFORM_ZONE } from "@/lib/host";
import { clearAuthCookies, getRefreshToken } from "@/lib/auth-cookies";

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

    response.cookies.set("owt_access_token", tokens.access_token, {
      httpOnly: false,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: getTokenMaxAgeSeconds(tokens.access_token, FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS),
      ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {})
    });

    response.cookies.set("owt_refresh_token", tokens.refresh_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: IS_PROD,
      path: "/",
      maxAge: 30 * 24 * 60 * 60,
      ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {})
    });

    return response;
  } catch {
    const response = NextResponse.json({ message: "Failed to refresh" }, { status: 401 });
    clearAuthCookies(response);
    return response;
  }
}
