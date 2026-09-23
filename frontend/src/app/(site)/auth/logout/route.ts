import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { getForwardedClientHeaders } from "@/lib/auth/forward-client-headers";
import { authService } from "@/services/auth.service";
import { clearAuthCookies, getAccessToken, getRefreshToken } from "@/lib/auth/cookies";

// POST only, and deliberately so. This endpoint revokes the refresh token and
// deletes the session cookies — a state change that must never ride on a GET,
// because a GET to a URL is something the *world* can trigger: a chat client
// unfurling a link preview, a corporate link scanner, an antivirus proxy, the
// browser's own speculative prefetch, "reopen all tabs". As a GET it was also
// one careless `<Link href="/auth/logout">` away from signing users out on
// hover. It answers 204 and lets the client navigate (see lib/auth/logout.ts), which
// also retires the old `next` parameter and its open-redirect clamp: the client
// stays on whatever host it is already on, so there is no redirect to validate.
export async function POST(request: Request) {
  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);
  const refreshToken = getRefreshToken(cookieStore);

  // Best-effort server-side logout (revoke refresh token). A failure here must
  // still clear the cookies below — the user asked to leave.
  try {
    if (accessToken && refreshToken) {
      await authService.logout(accessToken, refreshToken, getForwardedClientHeaders(request));
    }
  } catch {
    // ignore
  }

  const response = new NextResponse(null, { status: 204 });
  clearAuthCookies(response);
  return response;
}
