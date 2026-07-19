import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/forward-client-headers";
import { authService } from "@/services/auth.service";
import { clearAuthCookies, getAccessToken, getRefreshToken } from "@/lib/auth-cookies";
import { publicOrigin } from "@/lib/request-origin";

export async function GET(request: Request) {
  // Redirect back to the host the user is actually on (custom domain / subdomain
  // / apex), derived from forwarded headers — not request.url (0.0.0.0:3000
  // behind the edge) and not a fixed apex SITE_URL, which would kick a
  // custom-domain user over to the platform apex on logout. See request-origin.ts.
  const origin = publicOrigin(request);
  const url = new URL(request.url);
  const nextParam = url.searchParams.get("next");

  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);
  const refreshToken = getRefreshToken(cookieStore);

  // Best-effort server-side logout (revoke refresh token)
  try {
    if (accessToken && refreshToken) {
      await authService.logout(accessToken, refreshToken, getForwardedClientHeaders(request));
    }
  } catch {
    // ignore
  }

  // Validate redirect target to prevent open redirects (must stay same-origin).
  let safeNext = "/";
  if (nextParam) {
    try {
      const parsedNext = new URL(nextParam, origin);
      if (parsedNext.origin === origin) {
        safeNext = `${parsedNext.pathname}${parsedNext.search}`;
      }
    } catch {
      if (nextParam.startsWith("/")) {
        safeNext = nextParam;
      }
    }
  }

  // Redirect back onto the current host (custom domain / subdomain / apex).
  const redirectUrl = new URL(safeNext, origin);
  const response = NextResponse.redirect(redirectUrl);
  clearAuthCookies(response);
  return response;
}
