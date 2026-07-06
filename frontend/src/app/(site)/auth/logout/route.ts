import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { authService } from "@/services/auth.service";
import { PLATFORM_ZONE } from "@/lib/host";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

const IS_PROD = process.env.NODE_ENV === "production";
// owt_access_token/owt_refresh_token are Domain-wide cookies in production
// (oauth-callback.ts) — a delete without the same Domain attribute creates a
// second, host-only cookie of the same name instead of clearing the real one
// (RFC 6265 keys a cookie by name+domain+path), which would leave the user
// silently still logged in on every subdomain after "logging out."
const COOKIE_DOMAIN = `.${PLATFORM_ZONE}`;

function deleteOwtCookie(response: NextResponse, name: string): void {
  response.cookies.delete({
    name,
    path: "/",
    ...(IS_PROD ? { domain: COOKIE_DOMAIN } : {})
  });
}

export async function GET(request: Request) {
  const url = new URL(request.url);
  const nextParam = url.searchParams.get("next");

  const cookieStore = await cookies();
  const accessToken = cookieStore.get("owt_access_token")?.value ?? cookieStore.get("aqt_access_token")?.value;
  const refreshToken =
    cookieStore.get("owt_refresh_token")?.value ?? cookieStore.get("aqt_refresh_token")?.value;

  // Best-effort server-side logout (revoke refresh token)
  try {
    if (accessToken && refreshToken) {
      await authService.logout(accessToken, refreshToken, getForwardedClientHeaders(request));
    }
  } catch {
    // ignore
  }

  // Validate redirect target to prevent open redirects.
  let safeNext = "/";
  if (nextParam) {
    try {
      const parsedNext = new URL(nextParam, SITE_URL);
      const siteOrigin = new URL(SITE_URL).origin;
      if (parsedNext.origin === siteOrigin) {
        safeNext = `${parsedNext.pathname}${parsedNext.search}`;
      }
    } catch {
      if (nextParam.startsWith("/")) {
        safeNext = nextParam;
      }
    }
  }

  // Build redirect URL using SITE_URL to avoid 0.0.0.0 issues
  const redirectUrl = new URL(safeNext, SITE_URL);
  const response = NextResponse.redirect(redirectUrl);
  deleteOwtCookie(response, "owt_access_token");
  deleteOwtCookie(response, "owt_refresh_token");
  response.cookies.delete("aqt_access_token");
  response.cookies.delete("aqt_refresh_token");
  return response;
}
