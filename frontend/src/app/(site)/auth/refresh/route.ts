import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { getTokenMaxAgeSeconds } from "@/lib/jwt";
import { authService } from "@/services/auth.service";
import { PLATFORM_ZONE } from "@/lib/host";

// Cookie lifetime used when the access token's `exp` can't be decoded.
const FALLBACK_ACCESS_COOKIE_MAX_AGE_SECONDS = 13 * 60;

const IS_PROD = process.env.NODE_ENV === "production";
// owt_access_token/owt_refresh_token are set Domain-wide (SSO across
// subdomains) by oauth-callback.ts. A set/delete here without the same
// Domain attribute doesn't overwrite that cookie — RFC 6265 keys a cookie by
// (name, domain, path), so a host-only Set-Cookie would create a *second*,
// competing cookie of the same name instead of refreshing/clearing the real
// one. Must match exactly.
const COOKIE_DOMAIN = `.${PLATFORM_ZONE}`;

function deleteOwtCookie(response: NextResponse, name: string): void {
  response.cookies.delete({
    name,
    path: "/",
    ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {})
  });
}

export async function POST(request: Request) {
  const cookieStore = await cookies();
  const refreshToken =
    cookieStore.get("owt_refresh_token")?.value ?? cookieStore.get("aqt_refresh_token")?.value;

  if (!refreshToken) {
    const response = NextResponse.json({ message: "Missing refresh token" }, { status: 401 });
    deleteOwtCookie(response, "owt_access_token");
    deleteOwtCookie(response, "owt_refresh_token");
    response.cookies.delete("aqt_access_token");
    response.cookies.delete("aqt_refresh_token");
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
    deleteOwtCookie(response, "owt_access_token");
    deleteOwtCookie(response, "owt_refresh_token");
    response.cookies.delete("aqt_access_token");
    response.cookies.delete("aqt_refresh_token");
    return response;
  }
}
