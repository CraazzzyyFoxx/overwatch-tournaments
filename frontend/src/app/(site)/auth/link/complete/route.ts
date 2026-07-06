import { NextResponse } from "next/server";
import { cookies } from "next/headers";
import { authService } from "@/services/auth.service";
import { getAccessToken } from "@/lib/auth-cookies";
import { safeRedirectTarget } from "@/lib/oauth-callback";

// Far side of the custom-domain account-linking end-ticket (Task 10R). This
// route runs ON the workspace's custom domain itself -- never the platform
// apex -- after oauth-callback.ts's "link" branch has already
// authoritatively verified (via isVerifiedTenantOrigin/by_host,
// buildLinkTicketRedirect) that this exact origin is a real, resolvable
// workspace before ever redirecting the browser here. That check happened
// once, upstream; this route trusts it and focuses on resolving the LOCAL
// live session and redeeming the ticket against it.
//
// SECURITY INVARIANT #1: the linked-to site account is resolved from THIS
// request's own live session cookie -- the ticket carries ONLY the provider
// identity (see pending_link_tickets.py), never a site user id, and nothing
// here reads one from any URL/query param either. No session on this domain
// means there is nothing to link to, so this bounces to login rather than
// guessing or falling back to any identity the ticket might carry.
//
// Sets NO cookies: unlike /auth/sso/route.ts (which establishes a brand-new
// session from a ticket that DOES carry session tokens), linking never
// changes the caller's session here -- it only calls an authenticated RPC
// with the session that already exists.
function errorRedirect(origin: string, errorCode: string): NextResponse {
  const errorUrl = new URL("/", origin);
  errorUrl.searchParams.set("auth_error", errorCode);
  return NextResponse.redirect(errorUrl);
}

function loginRedirect(origin: string, next: string): NextResponse {
  const loginUrl = new URL("/", origin);
  loginUrl.searchParams.set("login", "1");
  loginUrl.searchParams.set("next", next);
  return NextResponse.redirect(loginUrl);
}

export async function GET(request: Request) {
  const { origin: currentOrigin, searchParams } = new URL(request.url);
  const ticket = searchParams.get("ticket");
  const next = searchParams.get("next") || "/account";

  if (!ticket) {
    return errorRedirect(currentOrigin, "invalid_state");
  }

  const cookieStore = await cookies();
  const accessToken = getAccessToken(cookieStore);

  if (!accessToken) {
    // Can't link without a live session on THIS domain (SECURITY INVARIANT
    // #1) -- send the user to log in, then retry from account settings.
    // Never fall back to any identity the ticket carries.
    return loginRedirect(currentOrigin, next);
  }

  try {
    await authService.completeLink(ticket, accessToken);
    return NextResponse.redirect(safeRedirectTarget(next, currentOrigin));
  } catch (err) {
    console.error("Link ticket exchange error:", err);
    return errorRedirect(currentOrigin, "exchange_failed");
  }
}
