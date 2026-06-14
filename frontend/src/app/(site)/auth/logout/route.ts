import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { authService } from "@/services/auth.service";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL || "http://localhost:3000";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const nextParam = url.searchParams.get("next");

  const cookieStore = await cookies();
  const accessToken = cookieStore.get("aqt_access_token")?.value;
  const refreshToken = cookieStore.get("aqt_refresh_token")?.value;

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
  response.cookies.delete("aqt_access_token");
  response.cookies.delete("aqt_refresh_token");
  return response;
}
